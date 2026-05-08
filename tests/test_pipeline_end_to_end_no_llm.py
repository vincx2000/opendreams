"""
End-to-end OpenDream pipeline run that makes ZERO LLM calls.

Exercises every stage by feeding hand-authored JSON in via the same
`--import-json` path the prompt-tuning loop uses:

    ingest claude_code → reflect --import-json → dream --import-json
                                              → memory export

Validates that the full chassis can run without an API key — useful for CI,
prompt-tuning workflows, and verifying schema changes don't break the loop.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from opendream import memory, store
from opendream.cli import app


REPO_ROOT = Path(__file__).parent.parent
CC_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "cc_session_c7ed2e78.jsonl"


def _reflection_payload_for(session_id: str) -> dict:
    """A v2-shaped Reflection JSON. The `session_id` is what the runner will
    inject; we leave it out and let `--import-json` add it."""
    return {
        "session_completeness": "interrupted",
        "reflection_confidence": "low",
        "target_task_classification": {
            "type": "other",
            "domain": "python project scaffolding",
            "complexity": "complex",
        },
        "observed_work_classification": {
            "type": "exploration",
            "domain": "python project scaffolding",
            "complexity": "moderate",
        },
        "approach": {
            "strategy_summary": "Agent did environment recon then was interrupted before scaffolding.",
            "tool_sequence": ["Bash"],
            "decision_points": [],
        },
        "observations": {
            "behaviors_observed": [
                {
                    "observation": "Agent ran reconnaissance bash calls before any mutating action.",
                    "evidence": "[2], [3]",
                    "confidence": "medium",
                    "scope": "generalizable",
                    "valence": "neutral",
                }
            ],
            "tool_use_notes": [],
            "context_observations": None,
        },
        "outcome": {
            "completed": False,
            "user_satisfied": "unclear",
            "evidence": "[Request interrupted by user]",
        },
        "candidates_for_memory": [
            {
                "kind": "pattern",
                "content": "Agent does environment reconnaissance (ls, git log, lang/version) before scaffolding-style tasks.",
                "scope": "generalizable",
                "evidence": "[2], [3]",
                "confidence": "low",
            }
        ],
    }


def _dream_payload_with_evidence(reflection_id: str) -> dict:
    """A DreamCycle JSON adding one entry to memory; reflections_considered
    is injected by `--import-json`."""
    return {
        "summary": "One pattern observed: recon-before-scaffold. Adding as a low-confidence pattern; promote on repetition.",
        "updates": [
            {
                "operation": "add",
                "kind": "pattern",
                "target_id": None,
                "content": "Agent does environment reconnaissance (ls, git log, lang/version) before scaffolding-style tasks.",
                "reason": "Observed once with clear evidence; flagged for cross-session reinforcement.",
                "evidence": [reflection_id],
                "confidence": "low",
                "scope": "generalizable",
            }
        ],
        "non_updates": [],
    }


def test_full_pipeline_no_llm_via_import_json(tmp_path):
    """ingest → reflect (imported) → dream (imported) → AGENTS.md export.
    Asserts every stage produces the expected artifact in the database."""
    db_path = tmp_path / "db.sqlite"
    agents_md = tmp_path / "AGENTS.md"
    runner = CliRunner()

    # 0. init
    r = runner.invoke(app, ["init", "--path", str(db_path)])
    assert r.exit_code == 0, r.stdout

    # 1. ingest a real (anonymized) Claude Code session
    r = runner.invoke(
        app,
        ["ingest", "claude_code", str(CC_FIXTURE), "--path", str(db_path)],
    )
    assert r.exit_code == 0, r.stdout
    sessions = store.list_sessions(path=db_path)
    assert len(sessions) == 1
    session_id = sessions[0].id

    # 2. import a hand-authored Reflection (no LLM call)
    r = runner.invoke(
        app,
        [
            "reflect",
            "--import-json",
            "--session-id",
            str(session_id),
            "--path",
            str(db_path),
        ],
        input=json.dumps(_reflection_payload_for(str(session_id))),
    )
    assert r.exit_code == 0, r.stdout
    assert "imported reflection" in r.stdout
    reflections = store.list_reflections(path=db_path)
    assert len(reflections) == 1
    ref = reflections[0]
    assert ref.session_id == session_id
    assert ref.session_completeness == "interrupted"
    assert ref.reflection_confidence == "low"
    assert ref.observations.behaviors_observed[0].valence == "neutral"

    # 3. import a hand-authored DreamCycle (no LLM call)
    r = runner.invoke(
        app,
        ["dream", "--import-json", "--path", str(db_path)],
        input=json.dumps(_dream_payload_with_evidence(str(ref.id))),
    )
    assert r.exit_code == 0, r.stdout
    assert "dream applied" in r.stdout

    cycles = store.list_dream_cycles(path=db_path)
    assert len(cycles) == 1
    assert cycles[0].applied is True
    assert cycles[0].reflections_considered == [ref.id]

    entries = store.list_memory_entries(path=db_path)
    assert len(entries) == 1
    assert entries[0].kind == "pattern"
    assert "reconnaissance" in entries[0].content

    # 4. export AGENTS.md
    r = runner.invoke(
        app,
        [
            "memory",
            "export",
            "--out",
            str(agents_md),
            "--path",
            str(db_path),
        ],
    )
    assert r.exit_code == 0, r.stdout
    text = agents_md.read_text()
    assert memory.BEGIN_MARKER in text
    assert memory.END_MARKER in text
    assert "### Pattern" in text
    assert "reconnaissance" in text


def test_full_pipeline_supports_import_json_from_file(tmp_path):
    """`--import-json --from <file>` is the alternative to stdin."""
    db_path = tmp_path / "db.sqlite"
    runner = CliRunner()
    runner.invoke(app, ["init", "--path", str(db_path)])
    runner.invoke(
        app,
        ["ingest", "claude_code", str(CC_FIXTURE), "--path", str(db_path)],
    )
    sid = store.list_sessions(path=db_path)[0].id

    # Reflection from file
    ref_file = tmp_path / "ref.json"
    ref_file.write_text(json.dumps(_reflection_payload_for(str(sid))))
    r = runner.invoke(
        app,
        [
            "reflect",
            "--import-json",
            "--session-id",
            str(sid),
            "--from",
            str(ref_file),
            "--path",
            str(db_path),
        ],
    )
    assert r.exit_code == 0, r.stdout

    # Dream from file
    ref_id = store.list_reflections(path=db_path)[0].id
    dream_file = tmp_path / "dream.json"
    dream_file.write_text(json.dumps(_dream_payload_with_evidence(str(ref_id))))
    r = runner.invoke(
        app,
        [
            "dream",
            "--import-json",
            "--from",
            str(dream_file),
            "--path",
            str(db_path),
        ],
    )
    assert r.exit_code == 0, r.stdout
    assert len(store.list_memory_entries(path=db_path)) == 1


def test_pipeline_round_trips_v2_schema_fields_through_storage(tmp_path):
    """The new v2 schema fields (session_completeness, reflection_confidence,
    valence) must survive the SQLite save/load cycle."""
    db_path = tmp_path / "db.sqlite"
    runner = CliRunner()
    runner.invoke(app, ["init", "--path", str(db_path)])
    runner.invoke(
        app,
        ["ingest", "claude_code", str(CC_FIXTURE), "--path", str(db_path)],
    )
    sid = store.list_sessions(path=db_path)[0].id

    runner.invoke(
        app,
        ["reflect", "--import-json", "--session-id", str(sid), "--path", str(db_path)],
        input=json.dumps(_reflection_payload_for(str(sid))),
    )

    # Load back from disk via store (not via CLI) — confirms the SQLite layer
    # didn't quietly drop the new fields.
    reloaded = store.list_reflections(path=db_path)[0]
    assert reloaded.session_completeness == "interrupted"
    assert reloaded.reflection_confidence == "low"
    assert reloaded.target_task_classification.type == "other"
    assert reloaded.observed_work_classification.type == "exploration"
    bo = reloaded.observations.behaviors_observed[0]
    assert bo.valence == "neutral"
    assert bo.scope == "generalizable"
