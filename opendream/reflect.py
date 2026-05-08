"""
opendream.reflect
-----------------

Stage 1 of the pipeline: turn a single Session into a structured Reflection.

Three call modes share the same code paths:
- `reflect_on(session)` — render prompt, call LLM, return Reflection.
- `render_prompt(session)` — used by `opendream reflect --dry-run` to print
  the formatted prompt without spending tokens.
- `reflection_from_json(data, session_id)` — used by
  `opendream reflect --import-json` to validate human/Claude.ai-supplied JSON
  against the schema and store it through the same path the LLM call would.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from opendream.llm import LLMClient
from opendream.trace import Reflection, Session


PROMPT_PATH = Path(__file__).parent / "prompts" / "reflect.md"
SYSTEM_PROMPT = "You are a meta-cognitive observer for an AI agent."


def render_prompt(
    session: Session,
    prompt_path: Path | None = None,
    max_message_chars: int | None = None,
) -> tuple[str, str]:
    """Return (system, user) prompts as they'd be sent to the LLM.

    `max_message_chars`: cap each rendered message body at N chars and append
    a `[truncated: M chars elided]` marker. `None` (default) preserves full
    content. Used to compress sessions where Write/Edit tool calls embed full
    file contents — a typical Claude Code session can balloon to 165K+ tokens
    that way, of which 90%+ is dead weight for reflection.
    """
    template = (prompt_path or PROMPT_PATH).read_text(encoding="utf-8")
    user_prompt = (
        template.replace(
            "{task_description}", session.task_description or "(unspecified)"
        )
        .replace(
            "{session_trace}",
            _render_session(session, max_message_chars=max_message_chars),
        )
        .replace("{outcome}", _render_outcome(session))
    )
    return SYSTEM_PROMPT, user_prompt


def reflection_from_json(data: dict, session_id: UUID | str) -> Reflection:
    """Validate a JSON dict against `Reflection`, injecting `session_id`."""
    payload = dict(data)
    payload["session_id"] = str(session_id)
    return Reflection.model_validate(payload)


def reflect_on(
    session: Session,
    client: LLMClient | None = None,
    prompt_path: Path | None = None,
    max_message_chars: int | None = None,
) -> Reflection:
    """Produce a Reflection for the given session via Stage 1."""
    system, user_prompt = render_prompt(session, prompt_path, max_message_chars)
    cli = client or LLMClient(purpose="reflect")
    data = cli.complete_json(system, user_prompt)
    return reflection_from_json(data, session.id)


def _render_session(session: Session, max_message_chars: int | None = None) -> str:
    """Render messages as `[index] role: content` blocks for the LLM."""
    lines: list[str] = []
    for m in session.messages:
        body = m.content.strip()
        if max_message_chars is not None and len(body) > max_message_chars:
            elided = len(body) - max_message_chars
            body = body[:max_message_chars] + f"\n[truncated: {elided} chars elided]"
        lines.append(f"[{m.index}] {m.role.value}: {body}")
    return "\n\n".join(lines)


def _render_outcome(session: Session) -> str:
    if not session.outcome_known:
        return "unknown"
    if session.outcome_success is True:
        return "success"
    if session.outcome_success is False:
        return "failure"
    return "unknown"
