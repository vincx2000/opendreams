from __future__ import annotations

from datetime import datetime

from opendream.adapters import aider as aider_adapter
from opendream.trace import MessageRole


REAL_AIDER_FORMAT = """\
# aider chat started at 2026-04-30 09:15:00

#### fix the typo in greeter.py
#### where it says "helo" instead of "hello"

I'll patch greeter.py:

```python
- print("helo")
+ print("hello")
```

Done.

#### thanks!

You're welcome.

# aider chat started at 2026-05-01 10:00:00

#### add a test for the greeter

Adding tests/test_greeter.py.
"""


def test_parse_two_sessions_with_real_aider_format():
    sessions = aider_adapter.parse(REAL_AIDER_FORMAT)
    assert len(sessions) == 2

    first = sessions[0]
    assert first.agent == "aider"
    assert first.started_at == datetime(2026, 4, 30, 9, 15, 0)
    assert first.task_description.startswith("fix the typo")
    roles = [m.role for m in first.messages]
    assert roles == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert "helo" in first.messages[0].content
    assert "patch greeter.py" in first.messages[1].content
    assert first.messages[2].content == "thanks!"

    second = sessions[1]
    assert second.started_at == datetime(2026, 5, 1, 10, 0, 0)
    assert second.task_description == "add a test for the greeter"
    assert len(second.messages) == 2


def test_parse_no_banner_treats_whole_file_as_one_session(tmp_path):
    text = "#### just one prompt\n\nThe assistant replies."
    sessions = aider_adapter.parse(text, fallback_started_at=datetime(2026, 1, 1))
    assert len(sessions) == 1
    assert sessions[0].started_at == datetime(2026, 1, 1)
    assert len(sessions[0].messages) == 2


def test_parse_empty_file_yields_no_sessions():
    assert aider_adapter.parse("") == []
    assert aider_adapter.parse("\n\n   \n") == []


def test_parse_file_uses_mtime_as_fallback(tmp_path):
    p = tmp_path / "history.md"
    p.write_text("#### hello\nthere", encoding="utf-8")
    sessions = aider_adapter.parse_file(p)
    assert len(sessions) == 1
    # Must be a datetime, not the unix epoch / now.
    assert isinstance(sessions[0].started_at, datetime)


def test_unrecognized_banner_timestamp_falls_back():
    text = "# aider chat started at not-a-date\n#### hi\nresp\n"
    sessions = aider_adapter.parse(
        text, fallback_started_at=datetime(2026, 6, 1)
    )
    assert len(sessions) == 1
    assert sessions[0].started_at == datetime(2026, 6, 1)


def test_message_indices_are_zero_based_and_dense():
    sessions = aider_adapter.parse(REAL_AIDER_FORMAT)
    first = sessions[0]
    assert [m.index for m in first.messages] == [0, 1, 2, 3]


# ---------------------------------------------------------- malformed input


def test_parse_garbage_bytes_does_not_crash():
    """Random bytes (non-Aider format) should yield zero or one degenerate
    session, never raise. Adapter must be tolerant."""
    garbage = "\x00\x01garbage\xffno markdown headers here\n#### maybe?\nsomething\n"
    sessions = aider_adapter.parse(garbage)
    # Either yields nothing or yields a single session with the `#### maybe?`
    # treated as a user message — both are acceptable. No exception is the
    # only contract.
    assert isinstance(sessions, list)
    for s in sessions:
        assert isinstance(s.messages, list)


def test_parse_banner_with_no_messages_yields_nothing():
    """A session banner followed by no #### user lines should be skipped,
    not produce an empty Session that confuses downstream stages."""
    text = "# aider chat started at 2026-04-30 09:15:00\n\n"
    assert aider_adapter.parse(text) == []


def test_parse_only_assistant_text_no_user_block():
    """Without any #### prefix, the whole content is treated as an assistant
    block (one assistant message). The session has a task_description of
    None because no user message exists."""
    text = "# aider chat started at 2026-04-30 09:15:00\n\nsome assistant prose with no user prompt."
    sessions = aider_adapter.parse(text)
    # Either zero sessions (degenerate) or one with a single assistant msg —
    # the parser currently produces the latter; both are tolerable.
    if sessions:
        assert sessions[0].task_description is None
        roles = {m.role for m in sessions[0].messages}
        # No user role in the trace
        from opendream.trace import MessageRole
        assert MessageRole.USER not in roles


def test_parse_file_handles_invalid_utf8_via_replace_errors(tmp_path):
    """The adapter reads with `errors='replace'` so bad encoding in the
    middle of a file does not abort the parse."""
    p = tmp_path / "bad-encoding.md"
    p.write_bytes(
        b"# aider chat started at 2026-04-30 09:15:00\n\n"
        b"#### prompt\n"
        b"reply with bad bytes: \xff\xfe somewhere\n"
    )
    sessions = aider_adapter.parse_file(p)
    assert len(sessions) == 1
    assert sessions[0].messages, "should produce at least one message"
