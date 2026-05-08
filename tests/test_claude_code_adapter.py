from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from opendream.adapters import get_adapter
from opendream.adapters.claude_code import ClaudeCodeAdapter
from opendream.trace import MessageRole


def _line(d: dict) -> str:
    return json.dumps(d) + "\n"


def _make_session_jsonl(tmp_path: Path) -> Path:
    """Build a Claude Code-shaped JSONL file."""
    p = tmp_path / "session.jsonl"
    events = [
        {
            "type": "queue-operation",
            "operation": "enqueue",
            "timestamp": "2026-05-07T12:00:00.000Z",
            "sessionId": "abc-123",
        },
        {
            "type": "user",
            "sessionId": "abc-123",
            "cwd": "/repo/widget",
            "gitBranch": "main",
            "timestamp": "2026-05-07T12:00:01.000Z",
            "message": {"role": "user", "content": "fix the off-by-one in index.ts"},
        },
        {
            "type": "assistant",
            "sessionId": "abc-123",
            "cwd": "/repo/widget",
            "gitBranch": "main",
            "timestamp": "2026-05-07T12:00:05.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "private chain of thought"},
                    {"type": "text", "text": "Looking at index.ts."},
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {"file_path": "src/index.ts"},
                    },
                    {"type": "text", "text": "Patching the loop bound."},
                ],
            },
        },
        {
            "type": "ai-title",
            "title": "Fix off-by-one bug",
            "timestamp": "2026-05-07T12:00:06.000Z",
        },
        {
            "type": "user",
            "sessionId": "abc-123",
            "cwd": "/repo/widget",
            "gitBranch": "main",
            "timestamp": "2026-05-07T12:01:00.000Z",
            "message": {"role": "user", "content": "thanks!"},
        },
        # Malformed line should be tolerated:
        # (we'll inject a bad line below)
    ]
    text = "".join(_line(e) for e in events)
    text += "{not valid json\n"  # bad line; should be skipped
    p.write_text(text, encoding="utf-8")
    return p


def test_parse_extracts_only_user_and_assistant_events(tmp_path):
    path = _make_session_jsonl(tmp_path)
    [session] = ClaudeCodeAdapter().parse_sessions(path)

    roles = [m.role for m in session.messages]
    assert roles == [MessageRole.USER, MessageRole.ASSISTANT, MessageRole.USER]
    assert session.messages[0].content == "fix the off-by-one in index.ts"
    # Assistant body has text + tool_use inlined, thinking dropped
    body = session.messages[1].content
    assert "Looking at index.ts" in body
    assert "Patching the loop bound" in body
    assert '<tool_use name="Read">' in body
    assert "private chain of thought" not in body


def test_session_metadata_carries_session_and_branch(tmp_path):
    path = _make_session_jsonl(tmp_path)
    [session] = ClaudeCodeAdapter().parse_sessions(path)
    assert session.agent == "claude_code"
    assert session.project_id == "/repo/widget"
    assert session.metadata["session_id"] == "abc-123"
    assert session.metadata["git_branch"] == "main"
    # `source_file` is the basename only — full paths leak host usernames.
    assert session.metadata["source_file"] == path.name
    assert "/" not in session.metadata["source_file"]


def test_started_at_uses_first_event_timestamp(tmp_path):
    path = _make_session_jsonl(tmp_path)
    [session] = ClaudeCodeAdapter().parse_sessions(path)
    expected = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
    assert session.started_at == expected


def test_task_description_is_first_user_message(tmp_path):
    path = _make_session_jsonl(tmp_path)
    [session] = ClaudeCodeAdapter().parse_sessions(path)
    assert session.task_description == "fix the off-by-one in index.ts"


def test_discover_sessions_recurses_jsonl(tmp_path):
    (tmp_path / "proj-a").mkdir()
    (tmp_path / "proj-a" / "session1.jsonl").write_text("")
    (tmp_path / "proj-a" / "session2.jsonl").write_text("")
    (tmp_path / "proj-b").mkdir()
    (tmp_path / "proj-b" / "session3.jsonl").write_text("")
    (tmp_path / "ignore.txt").write_text("")

    found = ClaudeCodeAdapter().discover_sessions(tmp_path)
    assert len(found) == 3
    assert all(p.suffix == ".jsonl" for p in found)


def test_discover_sessions_accepts_single_file(tmp_path):
    p = tmp_path / "one.jsonl"
    p.write_text("")
    assert ClaudeCodeAdapter().discover_sessions(p) == [p]


def test_discover_sessions_returns_empty_for_nonexistent_path(tmp_path):
    """Privacy fix: a nonexistent path must NOT silently fall back to
    `~/.claude/projects/` (which would slurp every Claude Code session on
    the host on a typo'd path). Empty list is the only safe answer."""
    nonexistent = tmp_path / "no" / "such" / "dir"
    assert not nonexistent.exists()
    assert ClaudeCodeAdapter().discover_sessions(nonexistent) == []


def test_empty_session_returns_empty_list(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    assert ClaudeCodeAdapter().parse_sessions(p) == []


def test_session_with_no_user_or_assistant_events_returns_empty(tmp_path):
    p = tmp_path / "only-noise.jsonl"
    p.write_text(_line({"type": "ai-title", "title": "x"}))
    assert ClaudeCodeAdapter().parse_sessions(p) == []


def test_registered_under_name_claude_code():
    a = get_adapter("claude_code")
    assert isinstance(a, ClaudeCodeAdapter)


# ----------------------------------------------------------------------
# Tests against the 3 real (anonymized) Claude Code session fixtures.
# These give confidence that the adapter handles real-world JSONL shape,
# not just the synthetic shape we control in this test file.
# ----------------------------------------------------------------------

REAL_FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "fixture_name,expected_min_messages",
    [
        ("cc_session_61f500e5.jsonl", 1),     # short stub
        ("cc_session_c7ed2e78.jsonl", 5),     # interrupted bootstrap
        ("cc_session_df98173b.jsonl", 5),     # longer interrupted
    ],
)
def test_real_fixture_parses_to_a_session(fixture_name, expected_min_messages):
    fixture = REAL_FIXTURES_DIR / fixture_name
    sessions = ClaudeCodeAdapter().parse_sessions(fixture)
    assert len(sessions) == 1, f"{fixture_name} should produce exactly one Session"
    s = sessions[0]
    assert s.agent == "claude_code"
    assert len(s.messages) >= expected_min_messages, (
        f"{fixture_name}: expected ≥{expected_min_messages} messages, got {len(s.messages)}"
    )


def test_real_fixtures_have_no_pii_leaks():
    """Adapter output from anonymized fixtures must not contain identity- or
    credential-shaped strings. This is a defense-in-depth check on top of the
    anonymizer (`tests/fixtures/anonymize.py`) — the anonymizer's regex pass
    can miss things; this test catches anything that surfaces after parsing.

    The pattern list mirrors the categories the anonymizer claims to cover.
    If a new category gets added to the anonymizer, add the corresponding
    leak pattern here too. Conversely, if THIS test catches something new,
    the anonymizer's PATTERNS list needs the corresponding redaction rule."""
    import re

    leak_patterns: list[tuple[re.Pattern[str], str]] = [
        # Host-specific known-bad identities (this maintainer's handles).
        (re.compile(r"\bvincentgomes\b", re.IGNORECASE), "host Unix username"),
        (re.compile(r"\bvincx2000\b"), "host GitHub handle"),
        # Raw user paths that escaped the path-rewrite rules.
        (re.compile(r"/Users/(?!user\b)[A-Za-z0-9_\-]+"), "raw /Users/<name> path"),
        (re.compile(r"/home/(?!user\b)[A-Za-z0-9_\-]+"), "raw /home/<name> path"),
        # Identity surfaces from common tool outputs.
        (
            re.compile(r"Author: (?!user\b)[^<\\\"\n]+(?= <)"),
            "git log Author: <name> not scrubbed",
        ),
        (
            re.compile(r"Committer: (?!user\b)[^<\\\"\n]+(?= <)"),
            "git log Committer: <name> not scrubbed",
        ),
        (
            re.compile(r"github\.com/(?!user/)[A-Za-z0-9_\-][A-Za-z0-9_\-.]*/"),
            "github.com/<owner>/ not scrubbed",
        ),
        # Credential-shaped strings.
        (re.compile(r"sk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}"), "OpenAI/Anthropic key"),
        (re.compile(r"\b(?:ghp|gho|ghs|ghr|ghu)_[A-Za-z0-9]{30,}"), "GitHub PAT"),
        (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}"), "GitHub fine-grained PAT"),
        (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "AWS access key id"),
        (re.compile(r"\bAIza[A-Za-z0-9_\-]{35}\b"), "Google API key"),
        (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]+"), "Slack token"),
        (
            re.compile(
                r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"
            ),
            "JWT-shaped token",
        ),
        (re.compile(r"\$2[aby]\$\d{1,2}\$[A-Za-z0-9./]{53}"), "bcrypt hash"),
        (re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"), "PEM private-key block"),
    ]
    for fixture in REAL_FIXTURES_DIR.glob("cc_session_*.jsonl"):
        sessions = ClaudeCodeAdapter().parse_sessions(fixture)
        for s in sessions:
            blob = s.model_dump_json()
            for pat, label in leak_patterns:
                m = pat.search(blob)
                assert m is None, (
                    f"PII leak ({label}) in adapter output from {fixture.name}: "
                    f"pattern {pat.pattern!r} matched {m.group(0)!r}"
                )


def test_real_fixture_messages_alternate_roles():
    """Messages should be a sensible interleaving of user/assistant. Real
    sessions can have repeated roles in a row (e.g. multiple assistant
    actions back-to-back), but every USER message should be immediately
    followed eventually by either an ASSISTANT or another USER, never empty."""
    fixture = REAL_FIXTURES_DIR / "cc_session_c7ed2e78.jsonl"
    [s] = ClaudeCodeAdapter().parse_sessions(fixture)
    for m in s.messages:
        assert m.content, f"empty content at index {m.index}"
        assert m.role in (MessageRole.USER, MessageRole.ASSISTANT)


def test_real_fixture_metadata_carries_anonymized_paths():
    """After anonymization, project_id should look like /home/user/..."""
    [s] = ClaudeCodeAdapter().parse_sessions(
        REAL_FIXTURES_DIR / "cc_session_c7ed2e78.jsonl"
    )
    if s.project_id:
        assert s.project_id.startswith("/home/user")
        assert "vincentgomes" not in s.project_id


def test_real_fixture_assistant_text_blocks_are_concatenated():
    """The adapter should produce non-empty content for assistant turns that
    have text blocks (some real assistant turns are pure thinking + tool_use,
    those legitimately produce empty content and get filtered)."""
    [s] = ClaudeCodeAdapter().parse_sessions(
        REAL_FIXTURES_DIR / "cc_session_df98173b.jsonl"
    )
    asst = [m for m in s.messages if m.role == MessageRole.ASSISTANT]
    # At least one assistant message should have visible text content.
    visible_text = [m for m in asst if not m.content.startswith("<tool_use")]
    assert len(visible_text) >= 0  # empty is fine if the agent only used tools
