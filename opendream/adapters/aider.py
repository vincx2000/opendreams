"""
opendream.adapters.aider
------------------------

Parser for Aider's `.aider.chat.history.md` format.

Real-world Aider history convention (slightly more specific than CLAUDE.md §15):
- A new session starts with a line matching `# aider chat started at <timestamp>`.
- User input is recorded as one or more *consecutive* lines prefixed with `#### `;
  each line carries one line of the user's prompt.
- Whatever non-`####` content follows — until the next `####` block or session
  banner — is the assistant's reply, including any inline tool/edit fences.

We tolerate noise: leading content before the first banner is ignored, banners
with unrecognized timestamp formats fall back to the file's mtime, and empty
sessions are dropped instead of crashing.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from opendream.trace import Message, MessageRole, Session


SESSION_BANNER = re.compile(r"^# aider chat started at\s+(.+?)\s*$")
USER_LINE = re.compile(r"^#### ?(.*)$")


def parse_file(path: Path | str) -> list[Session]:
    """Parse a `.aider.chat.history.md` file into a list of `Session`s."""
    p = Path(path)
    content = p.read_text(encoding="utf-8", errors="replace")
    fallback_ts = datetime.fromtimestamp(p.stat().st_mtime)
    return parse(content, fallback_started_at=fallback_ts, project_id=str(p.parent))


def parse(
    content: str,
    fallback_started_at: datetime | None = None,
    project_id: str | None = None,
) -> list[Session]:
    """Parse an Aider chat history string into `Session`s."""
    fallback = fallback_started_at or datetime.utcnow()
    sessions: list[Session] = []
    for started_at, body in _split_sessions(content, fallback):
        messages = list(_parse_messages(body))
        if not messages:
            continue
        first_user = next(
            (m.content for m in messages if m.role == MessageRole.USER), None
        )
        sessions.append(
            Session(
                agent="aider",
                project_id=project_id,
                started_at=started_at,
                task_description=first_user,
                messages=messages,
            )
        )
    return sessions


def _split_sessions(
    content: str, fallback: datetime
) -> Iterator[tuple[datetime, str]]:
    lines = content.splitlines()
    n = len(lines)

    banners: list[tuple[int, datetime]] = []
    for i, line in enumerate(lines):
        m = SESSION_BANNER.match(line)
        if m:
            banners.append((i, _parse_banner_ts(m.group(1), fallback)))

    if not banners:
        if content.strip():
            yield fallback, content
        return

    for idx, (banner_line, ts) in enumerate(banners):
        start = banner_line + 1
        end = banners[idx + 1][0] if idx + 1 < len(banners) else n
        yield ts, "\n".join(lines[start:end])


def _parse_banner_ts(s: str, fallback: datetime) -> datetime:
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return fallback


def _parse_messages(body: str) -> Iterator[Message]:
    lines = body.splitlines()
    i, n, idx = 0, len(lines), 0

    while i < n:
        if not lines[i].strip():
            i += 1
            continue

        first_match = USER_LINE.match(lines[i])
        if first_match:
            user_lines: list[str] = []
            while i < n:
                match = USER_LINE.match(lines[i])
                if not match:
                    break
                user_lines.append(match.group(1))
                i += 1
            content = "\n".join(user_lines).strip()
            if content:
                yield Message(index=idx, role=MessageRole.USER, content=content)
                idx += 1
            continue

        asst_lines: list[str] = []
        while i < n and not USER_LINE.match(lines[i]):
            asst_lines.append(lines[i])
            i += 1
        content = "\n".join(asst_lines).strip()
        if content:
            yield Message(index=idx, role=MessageRole.ASSISTANT, content=content)
            idx += 1
