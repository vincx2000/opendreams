from __future__ import annotations

from opendream import reflect


class StubLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, *, temperature: float = 0.0) -> dict:
        self.calls.append((system, user))
        return self.payload


REFLECTION_PAYLOAD = {
    "task_classification": {
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
        "what_worked": [
            {
                "observation": "the patch landed cleanly",
                "evidence": "[1]",
                "confidence": "medium",
                "scope": "task_specific",
            }
        ],
        "what_failed": [],
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
    assert ref.task_classification.type == "bug_fix"
    assert ref.observations.what_worked[0].observation == "the patch landed cleanly"
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
