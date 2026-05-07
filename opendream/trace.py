"""
opendream.trace
---------------

Data models for the entire pipeline. These lock in the schema for sessions,
reflections, and memory entries — every other module in OpenDream depends on
these. Keep them stable.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------- Session (Stage 0: ingested raw) ----------

class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class Message(BaseModel):
    """A single turn in an agent session."""
    index: int
    role: MessageRole
    content: str
    tool_name: str | None = None
    tool_input: dict | None = None
    tool_output: str | None = None
    timestamp: datetime | None = None


class Session(BaseModel):
    """A complete agent session, normalized across adapters."""
    id: UUID = Field(default_factory=uuid4)
    agent: str
    project_id: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    task_description: str | None = None
    messages: list[Message]
    outcome_known: bool = False
    outcome_success: bool | None = None
    metadata: dict = Field(default_factory=dict)


# ---------- Reflection (Stage 1 output) ----------

Confidence = Literal["low", "medium", "high"]
Scope = Literal["task_specific", "generalizable"]


class Observation(BaseModel):
    observation: str
    evidence: str
    confidence: Confidence
    scope: Scope


class ToolUseNote(BaseModel):
    tool: str
    note: str
    evidence: str


class DecisionPoint(BaseModel):
    moment: str
    choice_made: str
    alternatives_visible: str | None = None
    evidence: str


class TaskClassification(BaseModel):
    type: str
    domain: str
    complexity: Literal["trivial", "simple", "moderate", "complex"]


class Approach(BaseModel):
    strategy_summary: str
    tool_sequence: list[str]
    decision_points: list[DecisionPoint] = Field(default_factory=list)


class SessionObservations(BaseModel):
    what_worked: list[Observation] = Field(default_factory=list)
    what_failed: list[Observation] = Field(default_factory=list)
    tool_use_notes: list[ToolUseNote] = Field(default_factory=list)
    context_observations: str | None = None


class Outcome(BaseModel):
    completed: bool | Literal["unclear"]
    user_satisfied: bool | Literal["unclear"]
    evidence: str


MemoryKind = Literal["workflow", "pattern", "failure_mode", "preference", "fact"]


class MemoryCandidate(BaseModel):
    kind: MemoryKind
    content: str
    scope: Scope
    evidence: str
    confidence: Confidence


class Reflection(BaseModel):
    """Stage 1 output: one structured reflection per session."""
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    created_at: datetime = Field(default_factory=datetime.utcnow)
    task_classification: TaskClassification
    approach: Approach
    observations: SessionObservations
    outcome: Outcome
    candidates_for_memory: list[MemoryCandidate] = Field(default_factory=list)


# ---------- Consolidated memory (Stage 2 output applied) ----------

class MemoryEntry(BaseModel):
    """A single entry in the agent's long-term memory."""
    id: UUID = Field(default_factory=uuid4)
    kind: MemoryKind
    content: str
    scope: str
    confidence: Confidence
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_reinforced_at: datetime = Field(default_factory=datetime.utcnow)
    deprecated_at: datetime | None = None
    deprecation_reason: str | None = None
    evidence_reflection_ids: list[UUID] = Field(default_factory=list)


# ---------- Dream cycle (Stage 2 output) ----------

UpdateOp = Literal["add", "modify", "deprecate"]


class MemoryUpdate(BaseModel):
    """A proposed update produced by the consolidator."""
    operation: UpdateOp
    kind: MemoryKind
    target_id: UUID | None = None
    content: str | None = None
    reason: str
    evidence: list[UUID]
    confidence: Confidence
    scope: str


class NonUpdate(BaseModel):
    considered: str
    rejected_because: str


class DreamCycle(BaseModel):
    """The output of a single consolidation pass — a 'dream'."""
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reflections_considered: list[UUID]
    summary: str
    updates: list[MemoryUpdate]
    non_updates: list[NonUpdate] = Field(default_factory=list)
    applied: bool = False
    applied_at: datetime | None = None
