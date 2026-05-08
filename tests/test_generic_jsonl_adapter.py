from __future__ import annotations

import json

from opendream.adapters import get_adapter
from opendream.adapters.generic_jsonl import GenericJsonlAdapter
from opendream.trace import MessageRole


def _session_dict(agent: str = "my-stack", suffix: str = "0") -> dict:
    return {
        "agent": agent,
        "started_at": "2026-05-07T10:00:00",
        "task_description": f"task {suffix}",
        "messages": [
            {"index": 0, "role": "user", "content": f"do thing {suffix}"},
            {"index": 1, "role": "assistant", "content": f"done {suffix}"},
        ],
    }


def test_parse_multiple_sessions_one_per_line(tmp_path):
    p = tmp_path / "sessions.jsonl"
    payload = "".join(
        json.dumps(_session_dict(suffix=str(i))) + "\n" for i in range(3)
    )
    p.write_text(payload, encoding="utf-8")

    sessions = GenericJsonlAdapter().parse_sessions(p)
    assert len(sessions) == 3
    assert all(s.agent == "my-stack" for s in sessions)
    assert sessions[0].task_description == "task 0"
    assert sessions[2].messages[0].role == MessageRole.USER


def test_malformed_lines_are_skipped(tmp_path):
    p = tmp_path / "messy.jsonl"
    p.write_text(
        json.dumps(_session_dict(suffix="ok")) + "\n"
        "this is not json\n"
        "\n"
        + json.dumps({"missing": "fields"})  # validation will fail
        + "\n"
        + json.dumps(_session_dict(suffix="also-ok"))
        + "\n",
        encoding="utf-8",
    )
    sessions = GenericJsonlAdapter().parse_sessions(p)
    assert len(sessions) == 2
    assert {s.task_description for s in sessions} == {"task ok", "task also-ok"}


def test_empty_file(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    assert GenericJsonlAdapter().parse_sessions(p) == []


def test_discover_sessions_returns_jsonl_files(tmp_path):
    (tmp_path / "a.jsonl").write_text("")
    (tmp_path / "b.jsonl").write_text("")
    (tmp_path / "skipme.txt").write_text("")
    found = GenericJsonlAdapter().discover_sessions(tmp_path)
    assert len(found) == 2
    assert all(p.suffix == ".jsonl" for p in found)


def test_discover_sessions_accepts_single_file(tmp_path):
    p = tmp_path / "one.jsonl"
    p.write_text("")
    assert GenericJsonlAdapter().discover_sessions(p) == [p]


def test_round_trip_through_pydantic(tmp_path, sample_session):
    """A Session.model_dump_json() output should round-trip through the adapter."""
    p = tmp_path / "round.jsonl"
    p.write_text(sample_session.model_dump_json() + "\n", encoding="utf-8")
    [parsed] = GenericJsonlAdapter().parse_sessions(p)
    assert parsed.agent == sample_session.agent
    assert parsed.task_description == sample_session.task_description
    assert len(parsed.messages) == len(sample_session.messages)


def test_registered_under_name_generic_jsonl():
    a = get_adapter("generic_jsonl")
    assert isinstance(a, GenericJsonlAdapter)
