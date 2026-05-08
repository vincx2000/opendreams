"""End-to-end smoke test: ingest -> reflect (mocked) -> dream (mocked) -> export."""

from __future__ import annotations

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
    "task_classification": {
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
        "what_worked": [
            {
                "observation": "single-shot fix landed",
                "evidence": "[1]",
                "confidence": "medium",
                "scope": "task_specific",
            }
        ],
        "what_failed": [],
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
    out_md = tmp_path / "OPENDREAM.md"

    runner = CliRunner()

    # init
    r = runner.invoke(app, ["init", "--path", str(db_path)])
    assert r.exit_code == 0, r.stdout

    # ingest
    r = runner.invoke(
        app, ["ingest", "aider", str(history), "--path", str(db_path)]
    )
    assert r.exit_code == 0, r.stdout
    assert "ingested 1 session" in r.stdout

    # sessions list
    r = runner.invoke(app, ["sessions", "list", "--path", str(db_path)])
    assert r.exit_code == 0, r.stdout
    assert "fix the typo" in r.stdout

    # reflect (mock LLM)
    monkeypatch.setattr(reflect, "LLMClient", lambda: _StubLLM(REFLECT_PAYLOAD))
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
        lambda: _StubLLM(_consolidate_payload(refs)),
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
    assert "## Pattern" in text
    assert "agent handles trivial typo fixes" in text
