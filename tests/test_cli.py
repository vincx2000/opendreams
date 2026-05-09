"""End-to-end smoke test: ingest -> reflect (mocked) -> dream (mocked) -> export."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from opendream import consolidate, reflect, store
from opendream.cli import app


AIDER_HISTORY = """\
# aider chat started at 2026-04-30 09:15:00

#### fix the typo in greeter.py

Patching greeter.py to say "hello".

#### thanks!

You're welcome.
"""


REFLECT_PAYLOAD = {
    "session_completeness": "completed",
    "reflection_confidence": "medium",
    "target_task_classification": {
        "type": "bug_fix",
        "domain": "python",
        "complexity": "trivial",
    },
    "observed_work_classification": {
        "type": "bug_fix",
        "domain": "python",
        "complexity": "trivial",
    },
    "approach": {
        "strategy_summary": "patch then confirm",
        "tool_sequence": ["edit"],
        "decision_points": [],
    },
    "observations": {
        "behaviors_observed": [
            {
                "observation": "single-shot fix landed",
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
        "evidence": "user said thanks",
    },
    "candidates_for_memory": [
        {
            "kind": "pattern",
            "content": "agent fixes typos in one shot when the file is small",
            "scope": "generalizable",
            "evidence": "[1]",
            "confidence": "low",
        }
    ],
}


class _StubLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def complete_json(self, system: str, user: str, *, temperature: float = 0.0) -> dict:
        return self.payload


def _consolidate_payload(reflections):
    return {
        "summary": "single typo-fix reflection — too thin to consolidate yet",
        "updates": [
            {
                "operation": "add",
                "kind": "pattern",
                "target_id": None,
                "content": "agent handles trivial typo fixes in one shot",
                "reason": "supported by 1 reflection (low confidence)",
                "evidence": [str(r.id) for r in reflections],
                "confidence": "low",
                "scope": "generalizable",
            }
        ],
        "non_updates": [],
    }


def test_end_to_end_pipeline(monkeypatch, tmp_path):
    db_path = tmp_path / "db.sqlite"
    history = tmp_path / ".aider.chat.history.md"
    history.write_text(AIDER_HISTORY, encoding="utf-8")
    out_md = tmp_path / "AGENTS.md"

    runner = CliRunner()

    # init
    r = runner.invoke(app, ["init", "--path", str(db_path)])
    assert r.exit_code == 0, r.stdout

    # ingest (polymorphic)
    r = runner.invoke(
        app, ["ingest", "aider", str(history), "--path", str(db_path)]
    )
    assert r.exit_code == 0, r.stdout
    assert "ingested 1 session" in r.stdout
    assert "via aider" in r.stdout

    # sessions list
    r = runner.invoke(app, ["sessions", "list", "--path", str(db_path)])
    assert r.exit_code == 0, r.stdout
    assert "fix the typo" in r.stdout

    # reflect (mock LLM)
    monkeypatch.setattr(
        reflect, "LLMClient", lambda *a, **kw: _StubLLM(REFLECT_PAYLOAD)
    )
    r = runner.invoke(
        app, ["reflect", "--all-pending", "--path", str(db_path)]
    )
    assert r.exit_code == 0, r.stdout
    assert "reflected" in r.stdout
    assert len(store.list_reflections(path=db_path)) == 1

    # dream (mock LLM)
    refs = store.list_reflections(path=db_path)
    monkeypatch.setattr(
        consolidate,
        "LLMClient",
        lambda *a, **kw: _StubLLM(_consolidate_payload(refs)),
    )
    r = runner.invoke(app, ["dream", "--path", str(db_path)])
    assert r.exit_code == 0, r.stdout
    assert "dream applied" in r.stdout

    entries = store.list_memory_entries(path=db_path)
    assert len(entries) == 1
    assert entries[0].kind == "pattern"

    # export
    r = runner.invoke(
        app,
        ["memory", "export", "--out", str(out_md), "--path", str(db_path)],
    )
    assert r.exit_code == 0, r.stdout
    text = out_md.read_text()
    assert "<!-- OPENDREAM:BEGIN -->" in text
    assert "<!-- OPENDREAM:END -->" in text
    assert "### Pattern" in text
    assert "agent handles trivial typo fixes" in text


def test_reflect_all_pending_skips_validation_failures_and_continues(
    monkeypatch, tmp_path
):
    """Regression: when the LLM returns a malformed Reflection for one session
    (and the single retry also fails), --all-pending must log + skip that
    session, not abort the whole batch. Every other session should still get
    its reflection saved."""
    db_path = tmp_path / "db.sqlite"
    history = tmp_path / ".aider.chat.history.md"
    # Two distinct sessions in one aider history file.
    history.write_text(
        AIDER_HISTORY
        + "\n\n# aider chat started at 2026-05-01 10:00:00\n\n#### second task\n\nDone.\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    r = runner.invoke(app, ["init", "--path", str(db_path)])
    assert r.exit_code == 0
    r = runner.invoke(
        app, ["ingest", "aider", str(history), "--path", str(db_path)]
    )
    assert r.exit_code == 0
    sessions = store.list_sessions(path=db_path)
    assert len(sessions) == 2

    # Mock LLM: first session's two calls (initial + retry) both return a
    # malformed payload → that session is skipped. Second session's call
    # returns a valid payload → that one succeeds.
    malformed = {
        **REFLECT_PAYLOAD,
        "observations": {
            **REFLECT_PAYLOAD["observations"],
            "tool_use_notes": [{"tool": "Edit", "note": "used directly"}],  # missing evidence
        },
    }
    payloads = iter([malformed, malformed, REFLECT_PAYLOAD])

    class _SeqLLM:
        def complete_json(self, system, user, *, temperature=0.0):
            return next(payloads)

    monkeypatch.setattr(reflect, "LLMClient", lambda *a, **kw: _SeqLLM())

    r = runner.invoke(
        app, ["reflect", "--all-pending", "--path", str(db_path)]
    )
    assert r.exit_code == 0, r.stdout
    assert "skipped" in r.stdout
    assert "schema validation" in r.stdout
    # One reflection landed (for the second session), the first was skipped.
    refs = store.list_reflections(path=db_path)
    assert len(refs) == 1


def test_reflect_all_pending_skips_oversized_sessions_and_continues(
    monkeypatch, tmp_path
):
    """Regression: when a session's rendered prompt exceeds the model's context
    window, --all-pending must log + skip that session, not abort the batch.
    Mirrors the real Anthropic 400 'prompt is too long' failure mode."""
    db_path = tmp_path / "db.sqlite"
    history = tmp_path / ".aider.chat.history.md"
    history.write_text(
        AIDER_HISTORY
        + "\n\n# aider chat started at 2026-05-01 10:00:00\n\n#### second task\n\nDone.\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    runner.invoke(app, ["init", "--path", str(db_path)])
    runner.invoke(app, ["ingest", "aider", str(history), "--path", str(db_path)])
    sessions = store.list_sessions(path=db_path)
    assert len(sessions) == 2

    # First session: LLM raises the real Anthropic context-overflow error.
    # Second session: LLM returns a valid payload.
    call_count = {"n": 0}

    class _OversizedFirstLLM:
        def complete_json(self, system, user, *, temperature=0.0):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError(
                    "Error code: 400 - {'error': {'message': "
                    "'prompt is too long: 211977 tokens > 200000 maximum'}}"
                )
            return REFLECT_PAYLOAD

    monkeypatch.setattr(reflect, "LLMClient", lambda *a, **kw: _OversizedFirstLLM())

    r = runner.invoke(
        app, ["reflect", "--all-pending", "--path", str(db_path)]
    )
    assert r.exit_code == 0, r.stdout
    assert "skipped" in r.stdout
    assert "oversized" in r.stdout
    # Exactly one reflection saved (second session); first was skipped without
    # consuming a retry call.
    refs = store.list_reflections(path=db_path)
    assert len(refs) == 1
    assert call_count["n"] == 2, "expected 1 oversized call + 1 successful call (no retry on oversized)"


def test_ingest_aider_from_stdin(tmp_path):
    db_path = tmp_path / "db.sqlite"
    store.init_db(db_path)
    runner = CliRunner()

    r = runner.invoke(
        app,
        ["ingest", "aider", "-", "--path", str(db_path)],
        input=AIDER_HISTORY,
    )
    assert r.exit_code == 0, r.stdout
    assert "ingested 1 session" in r.stdout
    assert "<stdin>" in r.stdout
    assert len(store.list_sessions(path=db_path)) == 1


def test_ingest_unknown_adapter_errors_with_registry_listing(tmp_path):
    db_path = tmp_path / "db.sqlite"
    store.init_db(db_path)
    runner = CliRunner()
    r = runner.invoke(
        app, ["ingest", "nonexistent", "/dev/null", "--path", str(db_path)]
    )
    assert r.exit_code != 0
    output = r.stdout + (r.stderr or "")
    assert "unknown adapter" in output
    assert "claude_code" in output  # registry shown


def test_ingest_nonexistent_source_path_errors_cleanly(tmp_path):
    """Bad source path must raise a clean message, not a stack trace.

    Pre-fix bug: claude_code's discover_sessions silently fell back to
    `~/.claude/projects/` when the source didn't exist — privacy footgun
    on typo'd paths."""
    db_path = tmp_path / "db.sqlite"
    store.init_db(db_path)
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["ingest", "claude_code", "/no/such/path/xyz", "--path", str(db_path)],
    )
    assert r.exit_code != 0
    output = r.stdout + (r.stderr or "")
    assert "does not exist" in output
    # Should never silently slurp ~/.claude/projects/
    assert "ingested" not in output


def test_ingest_uninitialized_db_errors_cleanly(tmp_path, sample_session):
    """If the DB file doesn't exist, ingest tells the user to run `init`,
    instead of bubbling sqlite3.OperationalError."""
    src = tmp_path / "session.jsonl"
    src.write_text(sample_session.model_dump_json() + "\n", encoding="utf-8")
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "ingest",
            "generic_jsonl",
            str(src),
            "--path",
            str(tmp_path / "uninit.sqlite"),
        ],
    )
    assert r.exit_code != 0
    output = r.stdout + (r.stderr or "")
    assert "database not initialized" in output
    assert "opendream init" in output


def test_ingest_stdin_unlinks_tempfile_even_when_adapter_raises(tmp_path):
    """Regression: stdin ingest used `NamedTemporaryFile(delete=False)` and
    only unlinked on the success path. If `parse_sessions` raised, the temp
    file leaked. Now wrapped in try/finally.

    Direct attribute swap (not monkeypatch) because we need the patch on the
    `tempfile` module visible to the CLI's `tempfile.NamedTemporaryFile`
    call at runtime — pytest's monkeypatch tooling doesn't reach into
    CliRunner-invoked code paths the same way for module-level shims.
    """
    import tempfile as _tempfile

    db_path = tmp_path / "db.sqlite"
    store.init_db(db_path)

    real_named = _tempfile.NamedTemporaryFile
    created: list[Path] = []

    def tracking_named(*args, **kwargs):
        kwargs.setdefault("dir", str(tmp_path))
        f = real_named(*args, **kwargs)
        created.append(Path(f.name))
        return f

    # Make the adapter raise mid-parse so we exercise the finally path.
    from opendream.adapters import generic_jsonl

    def boom(self, path):
        raise RuntimeError("simulated parse failure")

    real_parse = generic_jsonl.GenericJsonlAdapter.parse_sessions
    _tempfile.NamedTemporaryFile = tracking_named
    generic_jsonl.GenericJsonlAdapter.parse_sessions = boom
    try:
        runner = CliRunner()
        r = runner.invoke(
            app,
            ["ingest", "generic_jsonl", "-", "--path", str(db_path)],
            input='{"agent": "x"}\n',
        )
    finally:
        _tempfile.NamedTemporaryFile = real_named
        generic_jsonl.GenericJsonlAdapter.parse_sessions = real_parse

    assert r.exit_code != 0  # adapter blew up; CLI should propagate
    assert created, "the test should have observed at least one tempfile"
    for p in created:
        assert not p.exists(), (
            f"tempfile {p} leaked after adapter raised "
            "(should have been unlinked in `finally`)"
        )


def test_ingest_generic_jsonl_round_trips(tmp_path, sample_session):
    db_path = tmp_path / "db.sqlite"
    store.init_db(db_path)
    src = tmp_path / "sessions.jsonl"
    src.write_text(sample_session.model_dump_json() + "\n", encoding="utf-8")

    runner = CliRunner()
    r = runner.invoke(
        app,
        ["ingest", "generic_jsonl", str(src), "--path", str(db_path)],
        input="",
    )
    assert r.exit_code == 0, r.stdout
    assert "ingested 1 session" in r.stdout
    assert "via generic_jsonl" in r.stdout
    assert len(store.list_sessions(path=db_path)) == 1


def test_memory_diff_lists_recent_dream_cycles(tmp_path):
    from datetime import datetime, timedelta
    from uuid import uuid4

    from opendream.trace import DreamCycle, MemoryUpdate

    db_path = tmp_path / "db.sqlite"
    store.init_db(db_path)

    old = DreamCycle(
        reflections_considered=[uuid4()],
        summary="ancient cycle",
        updates=[],
        applied=True,
        applied_at=datetime(2026, 1, 1),
    )
    recent = DreamCycle(
        reflections_considered=[uuid4()],
        summary="recent dream — added a pattern",
        updates=[
            MemoryUpdate(
                operation="add",
                kind="pattern",
                content="agent prefers small diffs",
                reason="seen across reflections",
                evidence=[uuid4()],
                confidence="high",
                scope="generalizable",
            )
        ],
        applied=True,
        applied_at=datetime.utcnow() - timedelta(hours=1),
    )
    store.save_dream_cycle(old, path=db_path)
    store.save_dream_cycle(recent, path=db_path)

    runner = CliRunner()
    cutoff = (datetime.utcnow() - timedelta(days=1)).isoformat(timespec="seconds")
    r = runner.invoke(
        app, ["memory", "diff", "--since", cutoff, "--path", str(db_path)]
    )
    assert r.exit_code == 0, r.stdout
    assert "recent dream" in r.stdout
    assert "ancient cycle" not in r.stdout
    assert "add" in r.stdout
    assert "pattern" in r.stdout


def test_memory_diff_rejects_bad_since():
    runner = CliRunner()
    r = runner.invoke(app, ["memory", "diff", "--since", "yesterday"])
    assert r.exit_code != 0
    assert "ISO 8601" in r.stdout or "ISO 8601" in (r.stderr or "")
