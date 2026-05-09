from __future__ import annotations

import pytest
from pydantic import ValidationError

from opendream import reflect


class StubLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, *, temperature: float = 0.0) -> dict:
        self.calls.append((system, user))
        return self.payload


class SequenceLLM:
    """Returns successive payloads on each call — simulates retry-with-feedback."""

    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, *, temperature: float = 0.0) -> dict:
        self.calls.append((system, user))
        if not self.payloads:
            raise AssertionError("SequenceLLM ran out of payloads")
        return self.payloads.pop(0)


REFLECTION_PAYLOAD = {
    "session_completeness": "completed",
    "reflection_confidence": "medium",
    "target_task_classification": {
        "type": "bug_fix",
        "domain": "python",
        "complexity": "simple",
    },
    "observed_work_classification": {
        "type": "bug_fix",
        "domain": "python",
        "complexity": "simple",
    },
    "approach": {
        "strategy_summary": "read then patch",
        "tool_sequence": ["read", "edit"],
        "decision_points": [],
    },
    "observations": {
        "behaviors_observed": [
            {
                "observation": "the patch landed cleanly",
                "evidence": "[1]",
                "confidence": "medium",
                "scope": "task_specific",
                "valence": "positive",
            }
        ],
        "tool_use_notes": [],
        "context_observations": None,
    },
    "outcome": {
        "completed": True,
        "user_satisfied": True,
        "evidence": "user said thanks",
    },
    "candidates_for_memory": [],
}


def test_reflect_on_returns_validated_reflection(sample_session):
    stub = StubLLM(REFLECTION_PAYLOAD)
    ref = reflect.reflect_on(sample_session, client=stub)

    assert ref.session_id == sample_session.id
    assert ref.target_task_classification.type == "bug_fix"
    assert ref.observed_work_classification.type == "bug_fix"
    assert ref.session_completeness == "completed"
    assert ref.reflection_confidence == "medium"
    assert ref.observations.behaviors_observed[0].observation == "the patch landed cleanly"
    assert ref.observations.behaviors_observed[0].valence == "positive"
    assert len(stub.calls) == 1


def test_reflect_on_renders_session_into_prompt(sample_session):
    stub = StubLLM(REFLECTION_PAYLOAD)
    reflect.reflect_on(sample_session, client=stub)

    _system, user = stub.calls[0]
    assert "fix the null pointer in parseUser" in user
    assert "[0] user:" in user
    assert "[1] assistant:" in user
    # Outcome rendering
    assert "success" in user


def test_reflect_on_handles_unknown_outcome(sample_session):
    sample_session.outcome_known = False
    sample_session.outcome_success = None
    stub = StubLLM(REFLECTION_PAYLOAD)
    reflect.reflect_on(sample_session, client=stub)
    _, user = stub.calls[0]
    assert "unknown" in user


def test_render_session_truncates_each_message(sample_session):
    """`max_message_chars` caps each message body and appends an elision marker."""
    long_body = "X" * 5000
    sample_session.messages[1].content = long_body

    full = reflect._render_session(sample_session, max_message_chars=None)
    capped = reflect._render_session(sample_session, max_message_chars=200)

    assert long_body in full
    assert long_body not in capped
    assert "[truncated: 4800 chars elided]" in capped
    # Other (short) messages are untouched
    assert sample_session.messages[0].content in capped


def test_render_session_no_cap_preserves_content(sample_session):
    """Default behavior is no truncation — all content preserved."""
    rendered = reflect._render_session(sample_session)
    for m in sample_session.messages:
        assert m.content in rendered


def _malformed_payload() -> dict:
    """Mirrors the real Haiku 4.5 failure mode: list entries missing required sub-fields."""
    bad = {
        **REFLECTION_PAYLOAD,
        "approach": {
            **REFLECTION_PAYLOAD["approach"],
            "decision_points": [{"moment": "chose to use Edit"}],  # missing choice_made + evidence
        },
        "observations": {
            **REFLECTION_PAYLOAD["observations"],
            "tool_use_notes": [{"tool": "Edit", "note": "used directly"}],  # missing evidence
        },
    }
    return bad


def test_reflect_on_retries_with_feedback_when_first_response_misses_fields(sample_session):
    """If the LLM drops required sub-fields, reflect_on retries once with the
    Pydantic error appended as feedback. Recovery on retry returns a valid Reflection."""
    stub = SequenceLLM([_malformed_payload(), REFLECTION_PAYLOAD])
    ref = reflect.reflect_on(sample_session, client=stub)

    assert ref.session_id == sample_session.id
    assert len(stub.calls) == 2, "expected exactly one retry"
    # Second call's user prompt must contain the validation feedback.
    _, retry_user = stub.calls[1]
    assert "failed schema validation" in retry_user
    assert "required" in retry_user.lower()


def test_reflect_on_propagates_validation_error_when_retry_also_fails(sample_session):
    """If the retry also returns a malformed payload, ValidationError propagates
    so the --all-pending caller can skip-and-continue."""
    stub = SequenceLLM([_malformed_payload(), _malformed_payload()])
    with pytest.raises(ValidationError):
        reflect.reflect_on(sample_session, client=stub)
    assert len(stub.calls) == 2, "must not retry more than once"


class _RaisingLLM:
    """Raises a chosen exception on `complete_json`."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, *, temperature: float = 0.0) -> dict:
        self.calls.append((system, user))
        raise self.exc


def test_reflect_on_maps_anthropic_oversized_prompt_to_oversized_session_error(sample_session):
    """Real failure mode: Anthropic 400 with `prompt is too long: N tokens > 200000 maximum`.
    `reflect.reflect_on` must convert that into `OversizedSessionError` so callers
    can distinguish it from transient errors."""
    raising = _RaisingLLM(
        RuntimeError(
            "Error code: 400 - {'error': {'message': "
            "'prompt is too long: 211977 tokens > 200000 maximum'}}"
        )
    )
    with pytest.raises(reflect.OversizedSessionError) as excinfo:
        reflect.reflect_on(sample_session, client=raising)
    assert "exceeds model context" in str(excinfo.value)
    assert len(raising.calls) == 1, "must not retry on oversized prompt"


def test_reflect_on_maps_openai_context_length_to_oversized_session_error(sample_session):
    """OpenAI surfaces context overflow as `context_length_exceeded`. Same handling."""
    raising = _RaisingLLM(
        RuntimeError("400 BadRequestError: context_length_exceeded — too many tokens")
    )
    with pytest.raises(reflect.OversizedSessionError):
        reflect.reflect_on(sample_session, client=raising)


def test_reflect_on_propagates_unrelated_errors_unchanged(sample_session):
    """Non-context-length errors (auth, rate limit, network) must propagate as-is
    so the user sees the real problem rather than a misleading skip."""
    raising = _RaisingLLM(RuntimeError("401 Unauthorized: bad API key"))
    with pytest.raises(RuntimeError, match="401"):
        reflect.reflect_on(sample_session, client=raising)


def test_render_prompt_forwards_max_message_chars(sample_session):
    """The CLI flag's value should propagate from render_prompt down to
    _render_session, AND the exact truncation-marker format must surface in
    the rendered prompt. Off-by-one risk if anyone touches the truncation
    logic — this assertion locks the full marker contract.
    """
    sample_session.messages[1].content = "Y" * 3000
    _, user_capped = reflect.render_prompt(sample_session, max_message_chars=100)
    _, user_full = reflect.render_prompt(sample_session, max_message_chars=None)

    # Exact marker text — `[truncated: <N> chars elided]` where N = total - cap.
    assert "[truncated: 2900 chars elided]" in user_capped, (
        "the truncation marker is missing from the rendered prompt; "
        "format string in opendream/reflect.py may have drifted"
    )
    assert "[truncated:" not in user_full

    # Body before the marker must stop at the cap (defense against off-by-one).
    head = "Y" * 100
    assert head in user_capped
    assert "Y" * 101 not in user_capped
