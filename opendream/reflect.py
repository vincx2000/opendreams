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

from pydantic import ValidationError

from opendream.llm import LLMClient
from opendream.trace import Reflection, Session


PROMPT_PATH = Path(__file__).parent / "prompts" / "reflect.md"
SYSTEM_PROMPT = "You are a meta-cognitive observer for an AI agent."


class OversizedSessionError(ValueError):
    """Session's rendered prompt exceeds the model's context window.

    Raised when the provider rejects the request with a context-length error
    (Anthropic: 'prompt is too long', OpenAI: 'context_length_exceeded').
    `--all-pending` callers skip-and-continue rather than aborting the batch,
    since this is a property of the session not a transient failure.
    """


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
    """Produce a Reflection for the given session via Stage 1.

    Single retry on ValidationError: cheaper Stage 1 models (Haiku, gpt-4o-mini)
    occasionally drop required sub-fields on list entries (e.g. omitting
    `evidence` on a `tool_use_notes` item). When that happens we re-prompt once
    with the Pydantic error appended as feedback. If the retry still fails, the
    ValidationError propagates — `--all-pending` callers should skip-and-continue.

    Oversized sessions (rendered prompt over the model's context window) are
    re-raised as `OversizedSessionError` so callers can distinguish them from
    transient failures and skip rather than retry.
    """
    system, user_prompt = render_prompt(session, prompt_path, max_message_chars)
    cli = client or LLMClient(purpose="reflect")
    try:
        data = cli.complete_json(system, user_prompt)
    except Exception as exc:
        if _is_context_length_error(exc):
            raise OversizedSessionError(
                f"session {session.id} rendered prompt exceeds model context: {exc}"
            ) from exc
        raise
    try:
        return reflection_from_json(data, session.id)
    except ValidationError as exc:
        feedback = (
            "\n\nYour previous response failed schema validation with these errors:\n"
            f"{exc}\n\n"
            "Return the JSON again with ALL required fields populated for every "
            "entry in every list. Do not omit any field marked required."
        )
        retry_data = cli.complete_json(system, user_prompt + feedback)
        return reflection_from_json(retry_data, session.id)


def _is_context_length_error(exc: BaseException) -> bool:
    """Detect provider 400s caused by prompt-too-long, across SDKs.

    Anthropic raises `anthropic.BadRequestError` with body
    `{'error': {'message': 'prompt is too long: N tokens > 200000 maximum'}}`.
    OpenAI raises `openai.BadRequestError` with `code='context_length_exceeded'`.
    Local OpenAI-compat backends sometimes wrap the same condition in a generic
    400 with vendor-specific phrasing — we match on common substrings.
    """
    msg = str(exc).lower()
    return (
        "prompt is too long" in msg
        or "context_length_exceeded" in msg
        or "context length" in msg
        or "maximum context length" in msg
        or "context window" in msg
    )


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
