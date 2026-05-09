"""
opendream.consolidate
---------------------

Stage 2 of the pipeline: the "dream" step. Reads a batch of new reflections
and the current consolidated memory, asks the LLM to propose updates, and
returns a `DreamCycle`. Application of the cycle is `memory.apply_cycle`.

Mirrors `reflect.py`'s split: a `render_prompt` for `--dry-run`, a
`dream_cycle_from_json` for `--import-json`, and `consolidate` that calls
the LLM normally.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from opendream.llm import LLMClient
from opendream.trace import DreamCycle, MemoryEntry, Reflection


PROMPT_PATH = Path(__file__).parent / "prompts" / "consolidate.md"
SYSTEM_PROMPT = "You are the consolidator for an AI agent's long-term memory."


def render_prompt(
    reflections: list[Reflection],
    current_memory: list[MemoryEntry],
    prompt_path: Path | None = None,
) -> tuple[str, str]:
    """Return (system, user) prompts as they'd be sent to the LLM."""
    template = (prompt_path or PROMPT_PATH).read_text(encoding="utf-8")
    user_prompt = template.replace(
        "{current_memory}", _render_memory(current_memory)
    ).replace("{new_reflections}", _render_reflections(reflections))
    return SYSTEM_PROMPT, user_prompt


def dream_cycle_from_json(
    data: dict, reflections: list[Reflection]
) -> DreamCycle:
    """Validate a JSON dict against `DreamCycle`, injecting `reflections_considered`."""
    payload = dict(data)
    payload["reflections_considered"] = [str(r.id) for r in reflections]
    return DreamCycle.model_validate(payload)


def consolidate(
    reflections: list[Reflection],
    current_memory: list[MemoryEntry],
    client: LLMClient | None = None,
    prompt_path: Path | None = None,
) -> DreamCycle:
    """Run a single dream cycle and return the proposed DreamCycle.

    Two single-retry guards, mirroring `reflect.reflect_on`:

    1. Truncation (`json.JSONDecodeError`) — large dream cycles occasionally
       overflow the 8192-token output cap and cut off mid-stream. Retry once
       with a 'be concise' nudge.
    2. Schema mismatch (`pydantic.ValidationError`) — common failure: model
       mangles a UUID (drops a hyphen, mistypes a group). Retry once with the
       Pydantic error fed back. UUIDs in `updates[].evidence` reference the
       reflection IDs, which are listed in the prompt verbatim.

    If a retry also fails the same check, the underlying error propagates.
    """
    system, user_prompt = render_prompt(reflections, current_memory, prompt_path)
    cli = client or LLMClient(purpose="dream")
    try:
        data = cli.complete_json(system, user_prompt)
    except json.JSONDecodeError:
        retry_prompt = user_prompt + (
            "\n\nYour previous response was not valid JSON (likely truncated). "
            "Return the JSON again. Keep `summary` concise (≤2 sentences) and "
            "prefer one sentence per update `content` field to fit the response budget."
        )
        data = cli.complete_json(system, retry_prompt)

    try:
        return dream_cycle_from_json(data, reflections)
    except ValidationError as exc:
        feedback = (
            "\n\nYour previous response failed schema validation with these errors:\n"
            f"{exc}\n\n"
            "Return the JSON again. Pay particular attention to UUID format — "
            "every `updates[].evidence[]` must be a 36-character canonical UUID "
            "(8-4-4-4-12 hex groups separated by hyphens), copied verbatim from "
            "the reflection IDs listed in the prompt."
        )
        retry_data = cli.complete_json(system, user_prompt + feedback)
        return dream_cycle_from_json(retry_data, reflections)


def _render_memory(entries: list[MemoryEntry]) -> str:
    if not entries:
        return "(empty — no memory consolidated yet)"
    return json.dumps(
        [
            {
                "id": str(e.id),
                "kind": e.kind,
                "content": e.content,
                "scope": e.scope,
                "confidence": e.confidence,
                "deprecated": e.deprecated_at is not None,
            }
            for e in entries
        ],
        indent=2,
    )


def _render_reflections(reflections: list[Reflection]) -> str:
    if not reflections:
        return "(none)"
    return json.dumps(
        [
            {
                "id": str(r.id),
                "session_id": str(r.session_id),
                "session_completeness": r.session_completeness,
                "reflection_confidence": r.reflection_confidence,
                "target_task_classification": r.target_task_classification.model_dump(),
                "observed_work_classification": r.observed_work_classification.model_dump(),
                "approach": r.approach.model_dump(),
                "observations": r.observations.model_dump(),
                "outcome": r.outcome.model_dump(),
                "candidates_for_memory": [c.model_dump() for c in r.candidates_for_memory],
            }
            for r in reflections
        ],
        indent=2,
    )
