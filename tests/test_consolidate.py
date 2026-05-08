from __future__ import annotations

from uuid import uuid4

from opendream import consolidate
from opendream.trace import (
    Approach,
    MemoryEntry,
    Outcome,
    Reflection,
    SessionObservations,
    TaskClassification,
)


class StubLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, *, temperature: float = 0.0) -> dict:
        self.calls.append((system, user))
        return self.payload


def _reflection() -> Reflection:
    return Reflection(
        session_id=uuid4(),
        task_classification=TaskClassification(
            type="bug_fix", domain="python", complexity="simple"
        ),
        approach=Approach(strategy_summary="patch", tool_sequence=["edit"]),
        observations=SessionObservations(),
        outcome=Outcome(completed=True, user_satisfied=True, evidence="green tests"),
    )


def test_consolidate_returns_dream_cycle_with_injected_reflection_ids():
    refs = [_reflection(), _reflection()]
    payload = {
        "summary": "two clean bug fixes",
        "updates": [],
        "non_updates": [],
    }
    stub = StubLLM(payload)

    cycle = consolidate.consolidate(refs, current_memory=[], client=stub)
    assert cycle.summary == "two clean bug fixes"
    assert cycle.reflections_considered == [r.id for r in refs]
    assert cycle.applied is False


def test_consolidate_renders_memory_and_reflections_into_prompt():
    ref = _reflection()
    existing = MemoryEntry(
        kind="pattern",
        content="prefers small diffs",
        scope="generalizable",
        confidence="high",
    )
    stub = StubLLM({"summary": "", "updates": [], "non_updates": []})

    consolidate.consolidate([ref], current_memory=[existing], client=stub)

    _system, user = stub.calls[0]
    assert "prefers small diffs" in user
    assert str(ref.id) in user
    assert "bug_fix" in user


def test_consolidate_with_empty_memory_renders_placeholder():
    stub = StubLLM({"summary": "", "updates": [], "non_updates": []})
    consolidate.consolidate([_reflection()], current_memory=[], client=stub)
    _system, user = stub.calls[0]
    assert "empty" in user.lower()
