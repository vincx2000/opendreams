"""Offline unit test for `run_two_pass_eval` — exercises the full
collect → consolidate → run orchestration without any LLM API calls.

The test substitutes:
- A fake `AgentRunner` that fabricates a stream-json transcript + creates a
  fake AGENTS.md hook so we can assert pass-2 received it.
- Stub LLM clients (duck-typed, `complete_json` only) injected via
  `reflect_client=` and `dream_client=`.

It verifies:
1. The eval store + transcript dir are wiped at the start of each run
   (no accumulation across re-runs).
2. Pass-1 captures one transcript per trial and writes them under
   `<workdir>/transcripts/<task>/trial-<n>/transcript.jsonl`.
3. The orchestrator ingests those transcripts, runs reflect + dream, and
   produces a real `<workdir>/AGENTS.md` between OPENDREAM markers.
4. Pass-2 receives `<workdir>/AGENTS.md` (not the project root's AGENTS.md).
5. Final `EvalReport` has both baseline and dreamed trials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from eval.runner import EvalTask, run_two_pass_eval


SAMPLE_TRANSCRIPT_LINES = [
    '{"type":"system","subtype":"init","cwd":"/tmp/x","session_id":"sess-1"}',
    '{"type":"user","message":{"role":"user","content":"please fix the bug"}}',
    (
        '{"type":"assistant","message":{"role":"assistant",'
        '"content":[{"type":"text","text":"I read the file and patched it."}]}}'
    ),
    '{"type":"result","subtype":"success"}',
]


REFLECTION_PAYLOAD = {
    "session_completeness": "completed",
    "reflection_confidence": "medium",
    "target_task_classification": {
        "type": "bug_fix",
        "domain": "python",
        "complexity": "simple",
    },
    "observed_work_classification": {
        "type": "bug_fix",
        "domain": "python",
        "complexity": "simple",
    },
    "approach": {
        "strategy_summary": "read then patch",
        "tool_sequence": ["read", "edit"],
        "decision_points": [],
    },
    "observations": {
        "behaviors_observed": [
            {
                "observation": "single-shot bug fix landed",
                "evidence": "[1]",
                "confidence": "medium",
                "scope": "task_specific",
                "valence": "positive",
            }
        ],
        "tool_use_notes": [],
        "context_observations": None,
    },
    "outcome": {
        "completed": True,
        "user_satisfied": True,
        "evidence": "agent reported success",
    },
    "candidates_for_memory": [
        {
            "kind": "pattern",
            "content": "agent fixes targeted bugs in one shot when scope is small",
            "scope": "generalizable",
            "evidence": "[1]",
            "confidence": "low",
        }
    ],
}


def _dream_payload(reflection_ids: list[str]) -> dict:
    return {
        "summary": "single bug fix consolidated",
        "updates": [
            {
                "operation": "add",
                "kind": "pattern",
                "target_id": None,
                "content": "agent handles small bug fixes in one shot",
                "reason": "single-session evidence; promote provisionally",
                "evidence": reflection_ids[:1],
                "confidence": "low",
                "scope": "generalizable",
            }
        ],
        "non_updates": [],
    }


class _StubLLM:
    """Returns a fixed payload on every `complete_json` call.

    Used for `reflect_client`: every captured transcript yields the same
    Reflection. Production paths use `LLMClient(purpose='reflect')` instead.
    """

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def complete_json(self, system: str, user: str, *, temperature: float = 0.0) -> dict:
        self.calls += 1
        return self.payload


class _DreamStubLLM:
    """Returns a payload computed from the *prompt* (so the dream cycle's
    `evidence` UUIDs match the real reflection IDs in the eval store)."""

    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, system: str, user: str, *, temperature: float = 0.0) -> dict:
        # The dream prompt embeds each Reflection as JSON, including its `id`.
        # We extract one id from the rendered prompt to use as evidence — this
        # mirrors what a real Sonnet response does and keeps the test honest
        # against UUID-validation logic in `dream_cycle_from_json`.
        import re
        ids = re.findall(
            r'"id":\s*"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"',
            user,
        )
        self.calls += 1
        return _dream_payload(ids)


@dataclass
class _FakeRunner:
    """Pretends to be `claude --print --output-format stream-json`.

    On `run()`, writes `SAMPLE_TRANSCRIPT_LINES` to `capture_to/transcript.jsonl`,
    records the workspace AGENTS.md if any was injected, and always returns
    True. Score functions on the eval tasks decide trial-level success.
    """

    capture_to: Path | None = None
    workspaces_seen: list[Path] = field(default_factory=list)
    agents_md_seen: list[Path | None] = field(default_factory=list)

    def run(self, task: EvalTask, workspace: Path, opendream_md: Path | None) -> bool:
        self.workspaces_seen.append(workspace)
        self.agents_md_seen.append(opendream_md)

        # Record AGENTS.md in workspace so pass-2 can assert it landed there
        # (production runner copies opendream_md → workspace/AGENTS.md).
        if opendream_md is not None:
            (workspace / "AGENTS.md").write_text(opendream_md.read_text())

        if self.capture_to is not None:
            self.capture_to.mkdir(parents=True, exist_ok=True)
            (self.capture_to / "transcript.jsonl").write_text(
                "\n".join(SAMPLE_TRANSCRIPT_LINES) + "\n"
            )
        return True


def _make_task(tmp_path: Path, task_id: str = "t01") -> EvalTask:
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True)
    (task_dir / "README.md").write_text(f"task {task_id}: please fix the bug")
    (task_dir / "score.py").write_text(
        "def score(workspace):\n    return True\n"
    )
    return EvalTask(task_id=task_id, task_dir=task_dir)


def _make_fixture(tmp_path: Path) -> Path:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "src.py").write_text("# nothing yet\n")
    return fixture


def test_two_pass_eval_orchestrates_collect_consolidate_run(tmp_path):
    """End-to-end: pass-1 captures → consolidate writes AGENTS.md →
    pass-2 receives AGENTS.md → final report contains both conditions."""
    task = _make_task(tmp_path)
    fixture = _make_fixture(tmp_path)
    workdir = tmp_path / "evalwd"
    runner = _FakeRunner()

    report = run_two_pass_eval(
        [task],
        runner,
        fixture_dir=fixture,
        trials=2,
        workdir=workdir,
        reflect_client=_StubLLM(REFLECTION_PAYLOAD),
        dream_client=_DreamStubLLM(),
    )

    # 1. Eval store + AGENTS.md exist
    assert (workdir / "store.sqlite").exists()
    agents_md = workdir / "AGENTS.md"
    assert agents_md.exists()
    md_body = agents_md.read_text()
    assert "<!-- OPENDREAM:BEGIN -->" in md_body
    assert "<!-- OPENDREAM:END -->" in md_body
    # The dream payload's update content must end up in the rendered AGENTS.md
    assert "agent handles small bug fixes" in md_body

    # 2. Transcripts captured per trial
    transcripts = list((workdir / "transcripts").rglob("transcript.jsonl"))
    assert len(transcripts) == 2, f"expected 2 transcripts, got {len(transcripts)}"

    # 3. Pass-2 received AGENTS.md (last 2 runs) — pass-1 did not (first 2)
    assert runner.agents_md_seen[:2] == [None, None]
    assert all(p is not None for p in runner.agents_md_seen[2:])
    # Pass-2 specifically gets the eval-store's AGENTS.md, NOT a project-root one
    for md_seen in runner.agents_md_seen[2:]:
        assert md_seen == agents_md

    # 4. Final report has 2 baseline + 2 dreamed trials, all successful
    assert len(report.trials) == 4
    assert sum(1 for t in report.trials if t.condition == "baseline") == 2
    assert sum(1 for t in report.trials if t.condition == "dreamed") == 2
    assert all(t.success for t in report.trials)


def test_two_pass_eval_wipes_state_on_consecutive_runs(tmp_path):
    """Re-running two-pass eval must NOT carry over the previous run's
    transcripts, sessions, or AGENTS.md — accumulating stale state would
    mix consolidated memory across runs and silently corrupt results."""
    task = _make_task(tmp_path)
    fixture = _make_fixture(tmp_path)
    workdir = tmp_path / "evalwd"

    # First run with one stub set
    run_two_pass_eval(
        [task],
        _FakeRunner(),
        fixture_dir=fixture,
        trials=1,
        workdir=workdir,
        reflect_client=_StubLLM(REFLECTION_PAYLOAD),
        dream_client=_DreamStubLLM(),
    )

    first_transcripts = sorted(p for p in (workdir / "transcripts").rglob("*.jsonl"))
    assert len(first_transcripts) == 1
    first_store_size = (workdir / "store.sqlite").stat().st_size

    # Inject a stale stray file inside transcripts dir to confirm wipe
    stray = workdir / "transcripts" / "stray.jsonl"
    stray.write_text("garbage\n")

    # Second run — same workdir, same trials, same task
    run_two_pass_eval(
        [task],
        _FakeRunner(),
        fixture_dir=fixture,
        trials=1,
        workdir=workdir,
        reflect_client=_StubLLM(REFLECTION_PAYLOAD),
        dream_client=_DreamStubLLM(),
    )

    assert not stray.exists(), "transcripts dir was not wiped between runs"
    second_transcripts = sorted(p for p in (workdir / "transcripts").rglob("*.jsonl"))
    assert len(second_transcripts) == 1, (
        "second run should produce exactly 1 transcript (not 2 — no accumulation)"
    )
    # store.sqlite was reset (init_db on a fresh file produces same byte size)
    second_store_size = (workdir / "store.sqlite").stat().st_size
    assert first_store_size == second_store_size, (
        "eval store was not wiped between runs — accumulating reflections would "
        "silently corrupt the consolidator's input"
    )


def test_two_pass_eval_rejects_runner_without_capture_support(tmp_path):
    """Runners that don't expose `capture_to` (e.g. `AiderRunner`) cannot be
    used for two-pass eval — the orchestrator must surface this as a clean
    error rather than silently producing an empty AGENTS.md."""
    task = _make_task(tmp_path)
    fixture = _make_fixture(tmp_path)

    class _NoCaptureRunner:
        def run(self, task, workspace, opendream_md):
            return True

    import pytest

    with pytest.raises(RuntimeError, match="does not support transcript capture"):
        run_two_pass_eval(
            [task],
            _NoCaptureRunner(),  # type: ignore[arg-type]
            fixture_dir=fixture,
            trials=1,
            workdir=tmp_path / "evalwd",
            reflect_client=_StubLLM(REFLECTION_PAYLOAD),
            dream_client=_DreamStubLLM(),
        )
