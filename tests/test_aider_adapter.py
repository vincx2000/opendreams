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
