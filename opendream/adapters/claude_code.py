"""
opendream.adapters.claude_code
------------------------------

Reads Claude Code session JSONL logs from `~/.claude/projects/<project>/<uuid>.jsonl`.

One file = one session. Each line is a JSON event with a `type`. v0 extracts
only `user` and `assistant` events; everything else (queue-operation,
file-history-snapshot, ai-title, attachment, last-prompt, …) is dropped.

Assistant content arrives as a list of structured blocks (`text`, `thinking`,
`tool_use`); we concatenate text blocks into the message body and inline tool
calls as `<tool_use name="…">...</tool_use>` markers so the reflection prompt
can still see what the agent did. Thinking blocks are dropped — they're long,
private, and the model produces them again on every turn.

Be tolerant: malformed lines and unknown event types are skipped, never
crashing the ingest of a long session because of one bad row.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from opendream.adapters.base import Adapter, register_adapter
from opendream.trace import Message, MessageRole, Session


DEFAULT_ROOT = Path.home() / ".claude" / "projects"
SESSION_GLOB = "*.jsonl"


@register_adapter
class ClaudeCodeAdapter(Adapter):
    name = "claude_code"

    def discover_sessions(self, root: Path) -> list[Path]:
        """Return every `*.jsonl` under `root`, recursively.

        If `root` is a single `.jsonl` file, return just that path. If it
        doesn't exist, return [] — the previous behavior (silently falling
        back to `~/.claude/projects/`) was a privacy footgun for typo'd
        paths. Pass `~/.claude/projects/` explicitly if you want all of it.
        """
        if not root.exists():
            return []
        if root.is_file() and root.suffix == ".jsonl":
            return [root]
        return sorted(root.rglob(SESSION_GLOB))

    def parse_sessions(self, path: Path) -> list[Session]:
        events = list(_iter_events(path))
        if not events:
            return []

        cwd = _first_value(events, "cwd")
        git_branch = _first_value(events, "gitBranch")
        # Claude Code's project-dir jsonl uses `sessionId` (camelCase). The
        # `--output-format stream-json` flag (used by the v0.0.2 two-pass eval
        # for transcript capture) emits the same field as `session_id`
        # (snake_case). Accept either so both ingestion paths work.
        session_id = _first_value(events, "sessionId") or _first_value(events, "session_id")
        started_at = _parse_ts(events[0].get("timestamp")) or datetime.fromtimestamp(
            path.stat().st_mtime
        )

        messages: list[Message] = []
        idx = 0
        first_user_text: str | None = None

        for event in events:
            etype = event.get("type")
            if etype == "user":
                content = _extract_user_content(event)
                if not content:
                    continue
                messages.append(
                    Message(
                        index=idx,
                        role=MessageRole.USER,
                        content=content,
                        timestamp=_parse_ts(event.get("timestamp")),
                    )
                )
                if first_user_text is None:
                    first_user_text = content
                idx += 1
            elif etype == "assistant":
                content = _extract_assistant_content(event)
                if not content:
                    continue
                messages.append(
                    Message(
                        index=idx,
                        role=MessageRole.ASSISTANT,
                        content=content,
                        timestamp=_parse_ts(event.get("timestamp")),
                    )
                )
                idx += 1

        if not messages:
            return []

        return [
            Session(
                agent="claude_code",
                project_id=cwd,
                started_at=started_at,
                task_description=first_user_text,
                messages=messages,
                metadata={
                    k: v
                    for k, v in {
                        "session_id": session_id,
                        "git_branch": git_branch,
                        # basename only — full paths leak the host username
                        # via `/Users/<name>/...` on macOS or `/home/<name>/...`
                        # on Linux. Use cwd / project_id for the full context.
                        "source_file": path.name,
                    }.items()
                    if v is not None
                },
            )
        ]


def _first_value(events: list[dict], key: str):
    """Return the first non-null value for `key` across events, or None."""
    for e in events:
        v = e.get(key)
        if v is not None:
            return v
    return None


def _iter_events(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # JS-style timestamps are "...Z"; Python's fromisoformat needs +00:00.
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_user_content(event: dict) -> str:
    msg = event.get("message", {})
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        # Some user events come in as block lists too (e.g. tool_result blocks).
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text"):
                parts.append(block["text"])
            elif block.get("type") == "tool_result":
                tc = block.get("content")
                if isinstance(tc, str):
                    parts.append(f"<tool_result>{tc}</tool_result>")
        return "\n".join(parts).strip()
    return ""


def _extract_assistant_content(event: dict) -> str:
    msg = event.get("message", {})
    blocks = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(blocks, list):
        return ""

    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = block.get("text") or ""
            if text:
                parts.append(text)
        elif btype == "tool_use":
            name = block.get("name", "?")
            tinput = block.get("input")
            input_repr = json.dumps(tinput, ensure_ascii=False) if tinput else ""
            parts.append(f'<tool_use name="{name}">{input_repr}</tool_use>')
        # Thinking blocks intentionally dropped.
    return "\n".join(parts).strip()
