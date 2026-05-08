"""
opendream.adapters.generic_jsonl
--------------------------------

Universal escape hatch: any project, regardless of agent framework, can emit a
JSONL file in this schema and immediately ingest into OpenDream.

Schema (one Session per line, see `docs/ADAPTERS.md` for the full spec):

    {"agent": "...",            (required)
     "started_at": "ISO 8601",  (required)
     "ended_at": "ISO 8601",    (optional)
     "task_description": "...", (optional)
     "project_id": "...",       (optional)
     "messages": [
        {"index": 0, "role": "user|assistant|tool|system", "content": "..."},
        ...
     ],
     "outcome_known": true,     (optional)
     "outcome_success": true,   (optional)
     "metadata": {}             (optional)
    }

Each line is validated against `trace.Session`. Malformed lines are skipped
with no fatal error so a single bad row doesn't poison a 10K-session export.
"""

from __future__ import annotations

import json
from pathlib import Path

from opendream.adapters.base import Adapter, register_adapter
from opendream.trace import Session


@register_adapter
class GenericJsonlAdapter(Adapter):
    name = "generic_jsonl"

    def discover_sessions(self, root: Path) -> list[Path]:
        """Return every `*.jsonl` file under `root`, or `root` itself if it's one."""
        if root.is_file():
            return [root]
        return sorted(root.rglob("*.jsonl"))

    def parse_sessions(self, path: Path) -> list[Session]:
        sessions: list[Session] = []
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    sessions.append(Session.model_validate(payload))
                except Exception:
                    # Pydantic validation failed; skip the row rather than aborting.
                    continue
        return sessions
