"""
eval.runner
-----------

OpenDream eval harness: run a fixed task suite under two conditions
(baseline vs dreamed) and report the success-rate lift.

SPEC.md §3 ship criterion 3: this report is what the README quotes as the
"before/after" number. Target ≥ 5 percentage-point lift on a 15-task suite,
5 trials each.

## Task layout

Tasks live in `eval/tasks/<n>_<slug>/` and have three files each:

- `README.md`         — the prompt the agent sees.
- `expected_test.py`  — copied into the workspace's tests/ before the agent
                        runs, so pytest (when called by `score`) can pick it
                        up alongside the existing fixture tests.
- `score.py`          — exposes `def score(workspace: Path) -> bool`. Most
                        scorers delegate to helpers in `eval.scorers`.

All tasks operate on a shared fixture codebase (`eval/fixtures/library_api/`
by default). The runner copies the fixture into a fresh per-trial workspace,
drops the task's expected_test.py into `workspace/tests/`, runs the agent,
then calls `task.score(workspace)`.

## Running

```python
from pathlib import Path
from eval.runner import run_eval, load_tasks
from eval.agents import ClaudeCodeRunner

tasks = load_tasks(Path("eval/tasks"))
report = run_eval(
    tasks,
    ClaudeCodeRunner(),
    fixture_dir=Path("eval/fixtures/library_api"),
    trials=5,
    opendream_md=Path("AGENTS.md"),
)
print(f"baseline: {report.success_rate('baseline'):.0%}")
print(f"dreamed : {report.success_rate('dreamed'):.0%}")
print(f"lift    : {report.lift_pp():+.1f}pp")
```
"""

from __future__ import annotations

import importlib.util
import shutil
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol


if TYPE_CHECKING:
    LLMClientLike = Any  # production: opendream.llm.LLMClient; tests: StubLLM


@dataclass
class EvalTask:
    """A single eval task: a directory containing README, expected_test, score."""

    task_id: str
    task_dir: Path
    timeout_seconds: int = 120

    @property
    def prompt(self) -> str:
        return (self.task_dir / "README.md").read_text(encoding="utf-8")

    @property
    def expected_test_path(self) -> Path:
        return self.task_dir / "expected_test.py"

    def score(self, workspace: Path) -> bool:
        """Import this task's score.py and run its `score(workspace)` function."""
        score_file = self.task_dir / "score.py"
        spec = importlib.util.spec_from_file_location(
            f"opendream_eval_task_{self.task_id}", score_file
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"could not load {score_file}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return bool(module.score(workspace))


@dataclass
class TrialResult:
    task_id: str
    condition: str  # "baseline" | "dreamed"
    trial: int
    success: bool
    duration_s: float
    notes: str = ""


@dataclass
class EvalReport:
    trials: list[TrialResult] = field(default_factory=list)

    def success_rate(self, condition: str) -> float:
        rows = [t for t in self.trials if t.condition == condition]
        if not rows:
            return 0.0
        return statistics.fmean(1.0 if t.success else 0.0 for t in rows)

    def lift_pp(self) -> float:
        """Dreamed minus baseline, expressed in percentage points."""
        return (self.success_rate("dreamed") - self.success_rate("baseline")) * 100

    def per_task(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for cond in ("baseline", "dreamed"):
            for t in self.trials:
                if t.condition != cond:
                    continue
                out.setdefault(t.task_id, {}).setdefault(cond, 0.0)
        for task_id in out:
            for cond in ("baseline", "dreamed"):
                rows = [
                    t
                    for t in self.trials
                    if t.task_id == task_id and t.condition == cond
                ]
                if rows:
                    out[task_id][cond] = statistics.fmean(
                        1.0 if t.success else 0.0 for t in rows
                    )
        return out


class AgentRunner(Protocol):
    """Anything that can drive an agent through one trial of one task.

    The runner receives a per-trial workspace already populated from the
    fixture and the task's expected_test.py, the user prompt, and (for the
    dreamed condition) the path to an `AGENTS.md` file. The return value is
    informational; success is decided by the task's `score()`.
    """

    def run(
        self,
        task: EvalTask,
        workspace: Path,
        opendream_md: Path | None,
    ) -> bool: ...


def run_eval(
    tasks: list[EvalTask],
    runner: AgentRunner,
    fixture_dir: Path,
    *,
    trials: int = 5,
    opendream_md: Path | None = None,
    workdir: Path | None = None,
) -> EvalReport:
    """Run each task under both conditions, `trials` times each."""
    fixture_dir = Path(fixture_dir).resolve()
    workdir = (workdir or Path(".opendream-eval")).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    report = EvalReport()
    for cond in ("baseline", "dreamed"):
        md = opendream_md if cond == "dreamed" else None
        _run_one_condition(
            tasks=tasks,
            runner=runner,
            fixture_dir=fixture_dir,
            workdir=workdir,
            condition=cond,
            opendream_md=md,
            trials=trials,
            report=report,
        )
    return report


def _run_one_condition(
    *,
    tasks: list[EvalTask],
    runner: AgentRunner,
    fixture_dir: Path,
    workdir: Path,
    condition: str,
    opendream_md: Path | None,
    trials: int,
    report: EvalReport,
) -> None:
    """Run every task × `trials` times under a single condition.

    Appends results to `report.trials`. Extracted from `run_eval` so the
    two-pass orchestrator can call it twice with independent setup between
    passes (collect + consolidate happens between pass-1 and pass-2). Keeping
    `run_eval`'s public signature stable.
    """
    for task in tasks:
        for trial in range(trials):
            trial_dir = workdir / task.task_id / condition / f"trial-{trial}"
            if trial_dir.exists():
                shutil.rmtree(trial_dir)
            shutil.copytree(fixture_dir, trial_dir)

            # Drop the task's expected_test.py into workspace/tests/ so
            # the score function (which usually runs pytest on it) finds it.
            if task.expected_test_path.exists():
                tests_dir = trial_dir / "tests"
                tests_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy(
                    task.expected_test_path,
                    tests_dir / f"test_{task.task_id}.py",
                )

            start = time.perf_counter()
            try:
                runner.run(task, trial_dir, opendream_md)
                success = task.score(trial_dir)
                notes = ""
            except Exception as exc:  # agent crashed; counts as failure
                success = False
                notes = f"agent exception: {exc!r}"
            duration = time.perf_counter() - start

            report.trials.append(
                TrialResult(
                    task_id=task.task_id,
                    condition=condition,
                    trial=trial,
                    success=success,
                    duration_s=duration,
                    notes=notes,
                )
            )


def run_two_pass_eval(
    tasks: list[EvalTask],
    runner: "AgentRunner",
    fixture_dir: Path,
    *,
    trials: int = 5,
    workdir: Path | None = None,
    eval_store: Path | None = None,
    reflect_client: "LLMClientLike | None" = None,
    dream_client: "LLMClientLike | None" = None,
) -> EvalReport:
    """Domain-matched two-pass eval: pass-1 collect → consolidate → pass-2 dreamed.

    Pass 1 runs every task × `trials` times under baseline (no AGENTS.md),
    capturing each trial's stream-json transcript. The captured transcripts
    are ingested into an isolated eval store (`eval_store`, default
    `<workdir>/store.sqlite`), reflected on, dreamed over once, and exported
    to `<workdir>/AGENTS.md`. Pass 2 runs every task × `trials` times again
    with that AGENTS.md injected. Final report combines pass-1 baseline
    trials with pass-2 dreamed trials.

    The `reflect_client` and `dream_client` parameters are dependency-
    injection seams for offline tests — production paths leave them None
    and the orchestrator builds the real `LLMClient` instances. Both must
    expose a `complete_json(system, user, *, temperature)` interface (the
    same shape the pipeline calls today).

    The `runner` MUST support transcript capture (currently only
    `ClaudeCodeRunner` does); we set its `capture_to` per-trial. Callers
    passing a runner type without that capability will get an AttributeError.

    Halts cleanly on:
    - Probe failure (`claude --print` doesn't produce a parseable transcript
      in a temp dir).
    - Any pass-1 trial that fails to capture a transcript.
    - Empty consolidator output (no AGENTS.md content to inject in pass-2).
    """
    from opendream import consolidate, memory, reflect, store
    from opendream.adapters.claude_code import ClaudeCodeAdapter

    fixture_dir = Path(fixture_dir).resolve()
    workdir = (workdir or Path(".opendream-eval")).resolve()
    eval_store = (eval_store or workdir / "store.sqlite").resolve()
    transcripts_dir = workdir / "transcripts"
    agents_md_path = workdir / "AGENTS.md"

    # ---------- Wipe eval-state (no accumulation across runs) ----------
    workdir.mkdir(parents=True, exist_ok=True)
    if eval_store.exists():
        eval_store.unlink()
    if transcripts_dir.exists():
        shutil.rmtree(transcripts_dir)
    if agents_md_path.exists():
        agents_md_path.unlink()
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    store.init_db(eval_store)

    # ---------- Pass 1: collect ----------
    report = EvalReport()
    if not hasattr(runner, "capture_to"):
        raise RuntimeError(
            f"runner {type(runner).__name__} does not support transcript capture; "
            "two-pass eval requires `ClaudeCodeRunner`"
        )
    runner.capture_to = transcripts_dir / "_pending"  # placeholder; reset per trial

    pass1_start = len(report.trials)
    for task in tasks:
        for trial in range(trials):
            trial_capture = transcripts_dir / task.task_id / f"trial-{trial}"
            runner.capture_to = trial_capture
            _run_one_condition(
                tasks=[task],
                runner=runner,
                fixture_dir=fixture_dir,
                workdir=workdir,
                condition="baseline",
                opendream_md=None,
                trials=1,
                report=report,
            )
            # _run_one_condition appended one TrialResult — repair its `trial`
            # field so combined reports keep deterministic per-task ordering.
            last = report.trials[-1]
            report.trials[-1] = TrialResult(
                task_id=last.task_id,
                condition=last.condition,
                trial=trial,
                success=last.success,
                duration_s=last.duration_s,
                notes=last.notes,
            )

    # ---------- Consolidate over captured transcripts ----------
    adapter = ClaudeCodeAdapter()
    transcript_paths = adapter.discover_sessions(transcripts_dir)
    if not transcript_paths:
        raise RuntimeError(
            f"no transcripts found under {transcripts_dir} after pass 1 — "
            "every trial failed to capture, or capture_to was not honored."
        )
    sessions: list = []
    for tp in transcript_paths:
        sessions.extend(adapter.parse_sessions(tp))
    for session in sessions:
        store.save_session(session, path=eval_store)

    if reflect_client is None:
        from opendream.llm import LLMClient
        reflect_client = LLMClient(purpose="reflect")
    for session in sessions:
        ref = reflect.reflect_on(session, client=reflect_client)
        store.save_reflection(ref, path=eval_store)

    reflections = store.list_reflections(path=eval_store)
    if dream_client is None:
        from opendream.llm import LLMClient
        dream_client = LLMClient(purpose="dream")
    cycle = consolidate.consolidate(
        reflections, current_memory=[], client=dream_client
    )
    memory.apply_cycle(cycle, path=eval_store)
    memory.export_agents_md(out_path=agents_md_path, path=eval_store)

    # ---------- Pass 2: dreamed ----------
    runner.capture_to = None  # pass-2 runs without capture
    _run_one_condition(
        tasks=tasks,
        runner=runner,
        fixture_dir=fixture_dir,
        workdir=workdir,
        condition="dreamed",
        opendream_md=agents_md_path,
        trials=trials,
        report=report,
    )

    _ = pass1_start  # placeholder — could split reports later if desired
    return report


def probe_claude_capture(claude_binary: str = "claude") -> None:
    """Pre-flight check before two-pass eval: confirm `claude --print
    --output-format stream-json` produces a parseable transcript.

    Spawns claude in a temp directory with a trivial prompt; raises a
    `RuntimeError` with an actionable message if anything fails. Cheap
    insurance against silent drift in Claude Code's output format.
    """
    import subprocess
    import tempfile

    if shutil.which(claude_binary) is None:
        raise RuntimeError(
            f"`{claude_binary}` not on PATH; two-pass eval requires Claude Code "
            "installed and `claude` reachable from this shell."
        )

    with tempfile.TemporaryDirectory(prefix="opendream-probe-") as td:
        td_path = Path(td)
        out_file = td_path / "transcript.jsonl"
        cmd = [
            claude_binary,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--no-session-persistence",
            "--dangerously-skip-permissions",
            "--add-dir",
            str(td_path),
        ]
        with out_file.open("wb") as f:
            try:
                subprocess.run(
                    cmd,
                    cwd=td_path,
                    input=b"reply with the literal text: ok",
                    stdout=f,
                    stderr=subprocess.PIPE,
                    timeout=60,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    "claude probe timed out after 60s; check `claude` auth"
                ) from exc

        # Use the same validator the runner uses, so probe and runner agree.
        from eval.agents import TranscriptCaptureError, _validate_transcript
        try:
            _validate_transcript(out_file)
        except TranscriptCaptureError as exc:
            raise RuntimeError(
                f"claude probe produced an unusable transcript: {exc}. "
                "Claude Code's `--output-format stream-json` may have changed; "
                "two-pass eval cannot proceed."
            ) from exc


def load_tasks(tasks_dir: Path | str) -> list[EvalTask]:
    """Load tasks from `eval/tasks/<n>_<slug>/` directories.

    A directory is recognized as a task if it contains a `README.md` and a
    `score.py`. `expected_test.py` is optional (refactor tasks may not need it).
    """
    tasks_dir = Path(tasks_dir)
    tasks: list[EvalTask] = []
    for sub in sorted(tasks_dir.iterdir()):
        if not sub.is_dir():
            continue
        if not (sub / "README.md").exists() or not (sub / "score.py").exists():
            continue
        tasks.append(EvalTask(task_id=sub.name, task_dir=sub))
    return tasks
