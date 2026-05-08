# Adapters

OpenDream's pipeline (`trace → reflect → consolidate → memory`) is
agent-framework-agnostic. The translation layer is the **adapter**: a small
class that takes whatever your stack already records (chat logs, JSONL, a
database, structured traces) and turns it into the normalized `Session` model
in [`opendream/trace.py`](../opendream/trace.py).

Three adapters ship in v0:

| Name             | Source                                          | When to use                                               |
| ---------------- | ----------------------------------------------- | --------------------------------------------------------- |
| `claude_code`    | `~/.claude/projects/<project>/<uuid>.jsonl`     | You're using Claude Code (the flagship case).             |
| `aider`          | `<repo>/.aider.chat.history.md`                 | You're using Aider.                                       |
| `generic_jsonl`  | Any `*.jsonl` file emitted in the schema below. | **Escape hatch** — anything else (OpenHands, Continue, Cline, custom). |

If your agent framework isn't in the table, you have two options:

1. **Easiest:** emit `generic_jsonl` from your stack's existing data. ~30 lines of code.
2. **Cleanest:** subclass `Adapter` (template at the bottom of this doc, ~50 lines).

---

## The `generic_jsonl` schema

**One file. One Session per line.** Each line is a JSON document that conforms
to `opendream.trace.Session`:

```json
{
  "agent": "my-agent-name",
  "started_at": "2026-05-07T10:00:00",
  "ended_at": "2026-05-07T10:42:13",
  "task_description": "Fix the off-by-one in src/index.ts",
  "project_id": "/Users/me/repos/widget-co",
  "outcome_known": true,
  "outcome_success": true,
  "messages": [
    {"index": 0, "role": "user",      "content": "Fix the off-by-one in src/index.ts"},
    {"index": 1, "role": "assistant", "content": "Inspecting the file...\n\n```ts\n...\n```"},
    {"index": 2, "role": "user",      "content": "great, ship it"}
  ],
  "metadata": {
    "git_branch": "main",
    "model": "claude-haiku-4-5"
  }
}
```

### Field reference

| Field              | Type                       | Required | Notes                                                                |
| ------------------ | -------------------------- | -------- | -------------------------------------------------------------------- |
| `agent`            | string                     | yes      | Free-form identifier (e.g. `"openhands"`, `"my-stack"`).             |
| `started_at`       | ISO 8601 datetime          | yes      | Session start.                                                       |
| `ended_at`         | ISO 8601 datetime or null  | no       | Optional.                                                            |
| `task_description` | string or null             | no       | Often the first user message; used for the `sessions list` summary.  |
| `project_id`       | string or null             | no       | Repo path or project identifier.                                     |
| `messages`         | array of Message objects   | yes      | At least one. See below.                                             |
| `outcome_known`    | bool                       | no       | Default `false`.                                                     |
| `outcome_success`  | bool or null               | no       | Only meaningful when `outcome_known=true`.                           |
| `metadata`         | object                     | no       | Free-form. Arbitrary keys.                                           |

Each `Message`:

| Field         | Type                                            | Required | Notes                                              |
| ------------- | ----------------------------------------------- | -------- | -------------------------------------------------- |
| `index`       | integer (0-based, dense)                        | yes      | Position in the message stream.                    |
| `role`        | `"user"` \| `"assistant"` \| `"tool"` \| `"system"` | yes  |                                                    |
| `content`     | string                                          | yes      | Plain text. Inline tool calls/edits are fine.      |
| `tool_name`   | string or null                                  | no       | Optional structured tool-call name.                |
| `tool_input`  | object or null                                  | no       | Optional structured tool-call input.               |
| `tool_output` | string or null                                  | no       | Optional tool result.                              |
| `timestamp`   | ISO 8601 datetime or null                       | no       | Per-message wall clock.                            |

### Producing the file from your stack

The simplest route is whatever flat-file-emitting code you already have. A
trivial example in Python:

```python
import json
from datetime import datetime
from pathlib import Path

def write_session_jsonl(out_path: Path, sessions: list[dict]) -> None:
    with out_path.open("a", encoding="utf-8") as f:
        for s in sessions:
            f.write(json.dumps(s, ensure_ascii=False, default=str) + "\n")
```

…then ingest with:

```bash
opendream ingest generic_jsonl path/to/sessions.jsonl
```

Malformed lines and Pydantic-validation failures are silently skipped, so a
single bad row will not poison a 10K-session dump.

---

## Writing a custom adapter (target: ≤ 50 lines)

Subclass `Adapter`, set a `name`, implement `discover_sessions` and
`parse_sessions`, and decorate with `@register_adapter`. That's it — `opendream
ingest <name> <path>` will pick it up automatically.

```python
# opendream/adapters/my_stack.py
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from opendream.adapters.base import Adapter, register_adapter
from opendream.trace import Message, MessageRole, Session


@register_adapter
class MyStackAdapter(Adapter):
    name = "my_stack"

    def discover_sessions(self, root: Path) -> list[Path]:
        # Return one Path per source file. If your format packs N sessions into
        # one file, that's fine — `parse_sessions` returns a list.
        if root.is_file():
            return [root]
        return sorted(root.rglob("*.session.log"))

    def parse_sessions(self, path: Path) -> list[Session]:
        # Read your stack's native format and yield zero-or-more Sessions.
        # Below is a stub showing the shape; replace with real parsing.
        text = path.read_text(encoding="utf-8")
        return [
            Session(
                agent=self.name,
                project_id=str(path.parent),
                started_at=datetime.fromtimestamp(path.stat().st_mtime),
                task_description="(parse from your data)",
                messages=[
                    Message(index=0, role=MessageRole.USER, content="..."),
                    Message(index=1, role=MessageRole.ASSISTANT, content="..."),
                ],
            )
        ]
```

Then register it by importing the module from `opendream/adapters/__init__.py`
(any in-tree adapter is auto-imported on package init), or — for adapters that
live outside this repo — `import opendream.adapters.my_stack` once at startup.

### Tips

- **Be tolerant.** Real-world logs are messy. Skip malformed sections rather
  than crashing; OpenDream's pipeline can tolerate ingesting fewer sessions, but
  cannot tolerate one bad row killing the rest.
- **Keep `content` plain text.** Inline tool calls are fine in the message
  body (e.g. `<tool_use name="Read">...</tool_use>`). Structured extraction
  is a v0.5 improvement.
- **Set `agent` to your adapter's `name`.** This lets reflections and dreams
  later filter or weight by source.
- **Don't pre-summarize.** Reflections (Stage 1) are the place for that — your
  job is to translate the raw history faithfully.
