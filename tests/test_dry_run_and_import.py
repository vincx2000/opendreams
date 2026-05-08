"""Tests for `--dry-run` and `--import-json` modes on reflect and dream."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from typer.testing import CliRunner

from opendream import consolidate, reflect, store
from opendream.cli import app
from opendream.trace import (
    Approach,
    DreamCycle,
    Outcome,
    Reflection,
    SessionObservations,
    TaskClassification,
)


REFLECT_JSON = {
    "session_completeness": "completed",
    "reflection_confidence": "low",
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
        "behaviors_observed": [],
        "tool_use_notes": [],
        "context_observations": None,
    },
    "outcome": {"completed": True, "user_satisfied": True, "evidence": "tests passed"},
    "candidates_for_memory": [],
}

DREAM_JSON = {
    "summary": "nothing surprising yet",
    "updates": [],
    "non_updates": [],
}


# ------------------------------------------------------------ render helpers


def test_reflect_render_prompt_substitutes_placeholders(sample_session):
    system, user = reflect.render_prompt(sample_session)
    assert "meta-cognitive observer" in system
    assert sample_session.task_description in user
    assert "[0] user:" in user
    assert "{task_description}" not in user
    assert "{session_trace}" not in user
    assert "{outcome}" not in user


def test_reflection_from_json_injects_session_id(sample_session):
    ref = reflect.reflection_from_json(REFLECT_JSON, sample_session.id)
    assert isinstance(ref, Reflection)
    assert ref.session_id == sample_session.id
    assert ref.target_task_classification.type == "bug_fix"
    assert ref.session_completeness == "completed"
    assert ref.reflection_confidence == "low"


def test_consolidate_render_prompt_substitutes_placeholders():
    refs = [
        Reflection(
            session_id=uuid4(),
            session_completeness="completed",
            reflection_confidence="medium",
            target_task_classification=TaskClassification(
                type="bug_fix", domain="py", complexity="trivial"
            ),
            observed_work_classification=TaskClassification(
                type="bug_fix", domain="py", complexity="trivial"
            ),
            approach=Approach(strategy_summary="x", tool_sequence=[]),
            observations=SessionObservations(),
            outcome=Outcome(completed=True, user_satisfied=True, evidence="green"),
        )
    ]
    system, user = consolidate.render_prompt(refs, current_memory=[])
    assert "consolidator" in system
    assert "{current_memory}" not in user
    assert "{new_reflections}" not in user
    assert str(refs[0].id) in user


def test_dream_cycle_from_json_injects_reflections_considered():
    ref_id = uuid4()
    refs = [
        Reflection(
            id=ref_id,
            session_id=uuid4(),
            session_completeness="completed",
            reflection_confidence="medium",
            target_task_classification=TaskClassification(
                type="bug_fix", domain="py", complexity="trivial"
            ),
            observed_work_classification=TaskClassification(
                type="bug_fix", domain="py", complexity="trivial"
            ),
            approach=Approach(strategy_summary="x", tool_sequence=[]),
            observations=SessionObservations(),
            outcome=Outcome(completed=True, user_satisfied=True, evidence="green"),
        )
    ]
    cycle = consolidate.dream_cycle_from_json(DREAM_JSON, refs)
    assert isinstance(cycle, DreamCycle)
    assert cycle.reflections_considered == [ref_id]


# ------------------------------------------------------------ reflect CLI


def _ingest(tmp_db: Path, sample_session) -> str:
    store.save_session(sample_session, path=tmp_db)
    return str(sample_session.id)


def test_reflect_dry_run_writes_prompt_file(tmp_db, sample_session, tmp_path, monkeypatch):
    """--dry-run writes the formatted prompt and makes NO LLM call."""
    sid = _ingest(tmp_db, sample_session)
    monkeypatch.setattr(
        "opendream.cli.DRYRUN_DIR", tmp_path / "od_dryrun"
    )
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["reflect", "--dry-run", "--session-id", sid, "--path", str(tmp_db)],
    )
    assert r.exit_code == 0, r.stdout
    out_file = tmp_path / "od_dryrun" / f"reflect_{sid}.txt"
    assert out_file.exists()
    text = out_file.read_text()
    assert "=== SYSTEM ===" in text
    assert "=== USER ===" in text
    assert sample_session.task_description in text


def test_reflect_dry_run_with_max_message_chars(tmp_db, sample_session, tmp_path, monkeypatch):
    """`--max-message-chars N` truncates message bodies in the rendered prompt."""
    sample_session.messages[1].content = "Z" * 5000
    sid = _ingest(tmp_db, sample_session)
    monkeypatch.setattr("opendream.cli.DRYRUN_DIR", tmp_path / "od_dryrun")

    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "reflect",
            "--dry-run",
            "--session-id",
            sid,
            "--max-message-chars",
            "200",
            "--path",
            str(tmp_db),
        ],
    )
    assert r.exit_code == 0, r.stdout
    text = (tmp_path / "od_dryrun" / f"reflect_{sid}.txt").read_text()
    assert "[truncated: 4800 chars elided]" in text
    assert "Z" * 5000 not in text


def test_reflect_dry_run_makes_no_llm_call(tmp_db, sample_session, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "opendream.cli.DRYRUN_DIR", tmp_path / "od_dryrun"
    )
    sid = _ingest(tmp_db, sample_session)

    def boom(*a, **kw):
        raise AssertionError("LLMClient must not be constructed in --dry-run")

    monkeypatch.setattr(reflect, "LLMClient", boom)
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["reflect", "--dry-run", "--session-id", sid, "--path", str(tmp_db)],
    )
    assert r.exit_code == 0, r.stdout
    assert store.list_reflections(path=tmp_db) == []


def test_reflect_import_json_from_stdin(tmp_db, sample_session, monkeypatch):
    sid = _ingest(tmp_db, sample_session)

    def boom(*a, **kw):
        raise AssertionError("LLMClient must not be constructed in --import-json")

    monkeypatch.setattr(reflect, "LLMClient", boom)

    runner = CliRunner()
    r = runner.invoke(
        app,
        ["reflect", "--import-json", "--session-id", sid, "--path", str(tmp_db)],
        input=json.dumps(REFLECT_JSON),
    )
    assert r.exit_code == 0, r.stdout
    assert "imported reflection" in r.stdout
    refs = store.list_reflections(path=tmp_db)
    assert len(refs) == 1
    assert refs[0].session_id == sample_session.id


def test_reflect_import_json_from_file(tmp_db, sample_session, tmp_path):
    sid = _ingest(tmp_db, sample_session)
    src = tmp_path / "ref.json"
    src.write_text(json.dumps(REFLECT_JSON), encoding="utf-8")

    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "reflect",
            "--import-json",
            "--session-id",
            sid,
            "--from",
            str(src),
            "--path",
            str(tmp_db),
        ],
    )
    assert r.exit_code == 0, r.stdout
    assert len(store.list_reflections(path=tmp_db)) == 1


def test_reflect_import_json_tolerates_markdown_fences(tmp_db, sample_session):
    sid = _ingest(tmp_db, sample_session)
    chatty = (
        "Sure! Here's the JSON you asked for:\n\n"
        "```json\n"
        + json.dumps(REFLECT_JSON, indent=2)
        + "\n```\n"
    )
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["reflect", "--import-json", "--session-id", sid, "--path", str(tmp_db)],
        input=chatty,
    )
    assert r.exit_code == 0, r.stdout
    assert len(store.list_reflections(path=tmp_db)) == 1


def test_reflect_dry_run_and_import_are_mutually_exclusive(tmp_db, sample_session):
    sid = _ingest(tmp_db, sample_session)
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "reflect",
            "--dry-run",
            "--import-json",
            "--session-id",
            sid,
            "--path",
            str(tmp_db),
        ],
    )
    assert r.exit_code != 0
    assert "mutually exclusive" in (r.stdout + (r.stderr or ""))


def test_reflect_import_json_requires_session_id(tmp_db):
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["reflect", "--import-json", "--all-pending", "--path", str(tmp_db)],
        input=json.dumps(REFLECT_JSON),
    )
    assert r.exit_code != 0


def test_reflect_from_without_import_is_rejected(tmp_db, tmp_path):
    f = tmp_path / "x.json"
    f.write_text("{}")
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["reflect", "--from", str(f), "--all-pending", "--path", str(tmp_db)],
    )
    assert r.exit_code != 0


# ------------------------------------------------------------ dream CLI


def _seed_reflection(tmp_db: Path, sample_session) -> Reflection:
    store.save_session(sample_session, path=tmp_db)
    tc = TaskClassification(type="bug_fix", domain="py", complexity="trivial")
    ref = Reflection(
        session_id=sample_session.id,
        session_completeness="completed",
        reflection_confidence="medium",
        target_task_classification=tc,
        observed_work_classification=tc,
        approach=Approach(strategy_summary="x", tool_sequence=[]),
        observations=SessionObservations(),
        outcome=Outcome(completed=True, user_satisfied=True, evidence="green"),
    )
    store.save_reflection(ref, path=tmp_db)
    return ref


def test_dream_dry_run_writes_prompt_file(tmp_db, sample_session, tmp_path, monkeypatch):
    _seed_reflection(tmp_db, sample_session)
    monkeypatch.setattr(
        "opendream.cli.DRYRUN_DIR", tmp_path / "od_dryrun"
    )

    def boom(*a, **kw):
        raise AssertionError("LLMClient must not be constructed in --dry-run")

    monkeypatch.setattr(consolidate, "LLMClient", boom)

    runner = CliRunner()
    r = runner.invoke(app, ["dream", "--dry-run", "--path", str(tmp_db)])
    assert r.exit_code == 0, r.stdout
    files = list((tmp_path / "od_dryrun").glob("dream_*.txt"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "=== SYSTEM ===" in text and "=== USER ===" in text
    # No DreamCycle was applied
    assert store.list_dream_cycles(path=tmp_db) == []


def test_dream_import_json_applies_cycle(tmp_db, sample_session, monkeypatch):
    ref = _seed_reflection(tmp_db, sample_session)

    def boom(*a, **kw):
        raise AssertionError("LLMClient must not be constructed in --import-json")

    monkeypatch.setattr(consolidate, "LLMClient", boom)

    payload = {
        "summary": "human-tuned dream",
        "updates": [
            {
                "operation": "add",
                "kind": "pattern",
                "target_id": None,
                "content": "imported by hand",
                "reason": "tuned",
                "evidence": [str(ref.id)],
                "confidence": "low",
                "scope": "generalizable",
            }
        ],
        "non_updates": [],
    }
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["dream", "--import-json", "--path", str(tmp_db)],
        input=json.dumps(payload),
    )
    assert r.exit_code == 0, r.stdout
    assert "dream applied" in r.stdout
    entries = store.list_memory_entries(path=tmp_db)
    assert len(entries) == 1
    assert entries[0].content == "imported by hand"


def test_dream_dry_run_and_import_mutually_exclusive(tmp_db, sample_session):
    _seed_reflection(tmp_db, sample_session)
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["dream", "--dry-run", "--import-json", "--path", str(tmp_db)],
        input="{}",
    )
    assert r.exit_code != 0
    assert "mutually exclusive" in (r.stdout + (r.stderr or ""))


# ---------------------------------------------------------- dream --review


class _StubLLM:
    """Tiny LLMClient stand-in for the --review tests below."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def complete_json(self, system, user, *, temperature: float = 0.0) -> dict:
        return self.payload


def test_dream_review_round_trip_via_fake_editor(tmp_db, sample_session, monkeypatch):
    """`--review` opens $EDITOR; if the user saves valid JSON the cycle applies."""
    ref = _seed_reflection(tmp_db, sample_session)

    # Stub LLMClient so the dream pipeline doesn't try to call out
    monkeypatch.setattr(
        consolidate, "LLMClient", lambda *a, **kw: _StubLLM({
            "summary": "test cycle",
            "updates": [
                {
                    "operation": "add",
                    "kind": "pattern",
                    "target_id": None,
                    "content": "original content",
                    "reason": "from llm",
                    "evidence": [str(ref.id)],
                    "confidence": "low",
                    "scope": "generalizable",
                }
            ],
            "non_updates": [],
        })
    )

    # Fake $EDITOR: a Python script that loads the JSON, mutates the content,
    # and writes back. monkeypatch EDITOR env to point at it.
    import sys as _sys
    editor_script = tmp_db.parent / "fake_editor.py"
    editor_script.write_text(
        "import json, sys\n"
        "with open(sys.argv[1]) as f:\n"
        "    obj = json.load(f)\n"
        "obj['updates'][0]['content'] = 'reviewed content'\n"
        "obj['summary'] = 'human-reviewed cycle'\n"
        "with open(sys.argv[1], 'w') as f:\n"
        "    json.dump(obj, f)\n"
    )
    monkeypatch.setenv("EDITOR", f"{_sys.executable} {editor_script}")

    runner = CliRunner()
    r = runner.invoke(app, ["dream", "--review", "--path", str(tmp_db)])
    assert r.exit_code == 0, r.stdout
    assert "dream applied" in r.stdout

    entries = store.list_memory_entries(path=tmp_db)
    assert len(entries) == 1
    # The reviewed (edited) content should have landed, not the original
    assert entries[0].content == "reviewed content"


def test_dream_review_abort_when_file_cleared(tmp_db, sample_session, monkeypatch):
    """Clearing the file in $EDITOR aborts the cycle without applying."""
    _seed_reflection(tmp_db, sample_session)

    monkeypatch.setattr(
        consolidate, "LLMClient", lambda *a, **kw: _StubLLM({
            "summary": "wasted",
            "updates": [],
            "non_updates": [],
        })
    )

    import sys as _sys
    editor_script = tmp_db.parent / "clear_editor.py"
    editor_script.write_text(
        "import sys\n"
        "open(sys.argv[1], 'w').close()\n"
    )
    monkeypatch.setenv("EDITOR", f"{_sys.executable} {editor_script}")

    runner = CliRunner()
    r = runner.invoke(app, ["dream", "--review", "--path", str(tmp_db)])
    assert r.exit_code == 0, r.stdout
    assert "review aborted" in r.stdout
    assert store.list_memory_entries(path=tmp_db) == []
    # Cycle should NOT have been saved because user aborted before save_dream_cycle
    assert store.list_dream_cycles(path=tmp_db) == []
