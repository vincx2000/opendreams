from __future__ import annotations

import json
from uuid import uuid4

import pytest

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
    tc = TaskClassification(type="bug_fix", domain="python", complexity="simple")
    return Reflection(
        session_id=uuid4(),
        session_completeness="completed",
        reflection_confidence="medium",
        target_task_classification=tc,
        observed_work_classification=tc,
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


class _SequenceLLM:
    """First N calls each raise from the configured queue; subsequent calls return payloads."""

    def __init__(self, results: list) -> None:
        # Each item is either a dict (returned) or an Exception (raised).
        self.results = list(results)
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, *, temperature: float = 0.0) -> dict:
        self.calls.append((system, user))
        if not self.results:
            raise AssertionError("_SequenceLLM ran out of results")
        head = self.results.pop(0)
        if isinstance(head, BaseException):
            raise head
        return head


def test_consolidate_retries_with_concise_nudge_on_truncated_output():
    """Real failure mode: large dream cycles overflow the output-token budget,
    yielding mid-stream-truncated JSON. consolidate() retries once with a
    'be concise' nudge appended to the prompt."""
    payload = {"summary": "ok", "updates": [], "non_updates": []}
    stub = _SequenceLLM(
        [json.JSONDecodeError("Expecting ',' delimiter", "trunc", 14287), payload]
    )
    cycle = consolidate.consolidate([_reflection()], current_memory=[], client=stub)
    assert cycle.summary == "ok"
    assert len(stub.calls) == 2
    _, retry_user = stub.calls[1]
    assert "previous response was not valid JSON" in retry_user
    assert "concise" in retry_user.lower()


def test_consolidate_propagates_json_error_when_retry_also_truncates():
    """If the retry also returns malformed JSON, the JSONDecodeError propagates
    so the user sees the underlying issue rather than a silent skip."""
    err = json.JSONDecodeError("Expecting ',' delimiter", "trunc", 14287)
    stub = _SequenceLLM([err, err])
    with pytest.raises(json.JSONDecodeError):
        consolidate.consolidate([_reflection()], current_memory=[], client=stub)
    assert len(stub.calls) == 2, "must not retry more than once"


def test_consolidate_retries_with_feedback_on_malformed_uuid():
    """Real failure mode: Sonnet 4.6 occasionally drops a hyphen in a UUID
    (`d7bf93c4-1eea40ba-84f0-...` instead of `d7bf93c4-1eea-40ba-84f0-...`),
    causing pydantic UUID validation to fail. consolidate() retries once with
    the Pydantic error fed back as feedback."""
    refs = [_reflection()]
    bad_uuid = str(refs[0].id).replace("-", "", 1)  # drop the first hyphen
    malformed = {
        "summary": "ok",
        "updates": [
            {
                "operation": "add",
                "kind": "pattern",
                "target_id": None,
                "content": "x",
                "reason": "y",
                "evidence": [bad_uuid],
                "confidence": "low",
                "scope": "task_specific",
            }
        ],
        "non_updates": [],
    }
    valid = {
        "summary": "ok",
        "updates": [
            {
                "operation": "add",
                "kind": "pattern",
                "target_id": None,
                "content": "x",
                "reason": "y",
                "evidence": [str(refs[0].id)],
                "confidence": "low",
                "scope": "task_specific",
            }
        ],
        "non_updates": [],
    }
    stub = _SequenceLLM([malformed, valid])
    cycle = consolidate.consolidate(refs, current_memory=[], client=stub)
    assert len(cycle.updates) == 1
    assert len(stub.calls) == 2
    _, retry_user = stub.calls[1]
    assert "schema validation" in retry_user
    assert "UUID" in retry_user


def test_consolidate_propagates_validation_error_when_retry_also_fails():
    """If the retry also returns malformed UUIDs, the ValidationError propagates."""
    refs = [_reflection()]
    bad_uuid = str(refs[0].id).replace("-", "", 1)
    malformed = {
        "summary": "ok",
        "updates": [
            {
                "operation": "add",
                "kind": "pattern",
                "target_id": None,
                "content": "x",
                "reason": "y",
                "evidence": [bad_uuid],
                "confidence": "low",
                "scope": "task_specific",
            }
        ],
        "non_updates": [],
    }
    from pydantic import ValidationError as _VE
    stub = _SequenceLLM([malformed, malformed])
    with pytest.raises(_VE):
        consolidate.consolidate(refs, current_memory=[], client=stub)
    assert len(stub.calls) == 2, "must not retry more than once"
