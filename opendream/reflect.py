"""
opendream.reflect
-----------------

Stage 1 of the pipeline: turn a single Session into a structured Reflection.

Loads `prompts/reflect.md`, fills in the session-specific slots, calls the LLM,
and parses the JSON response into a `Reflection`. The `session_id` is injected
on our side rather than asked of the model.
"""

from __future__ import annotations

from pathlib import Path

from opendream.llm import LLMClient
from opendream.trace import Reflection, Session


PROMPT_PATH = Path(__file__).parent / "prompts" / "reflect.md"
SYSTEM_PROMPT = "You are a meta-cognitive observer for an AI agent."


def reflect_on(
    session: Session,
    client: LLMClient | None = None,
    prompt_path: Path | None = None,
) -> Reflection:
    """Produce a Reflection for the given session via Stage 1."""
    template = (prompt_path or PROMPT_PATH).read_text(encoding="utf-8")
    user_prompt = (
        template.replace("{task_description}", session.task_description or "(unspecified)")
        .replace("{session_trace}", _render_session(session))
        .replace("{outcome}", _render_outcome(session))
    )

    cli = client or LLMClient()
    data = cli.complete_json(SYSTEM_PROMPT, user_prompt)
    data["session_id"] = str(session.id)
    return Reflection.model_validate(data)


def _render_session(session: Session) -> str:
    """Render messages as `[index] role: content` blocks for the LLM."""
    lines: list[str] = []
    for m in session.messages:
        body = m.content.strip()
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
