# OpenDream — full specification

You are bootstrapping **OpenDream** from an empty directory. This file is the entire specification. It contains the project mission, the architecture, every technical decision, the complete contents of the data models, both meta-prompts, the full `pyproject.toml`, the build sequence, and the precise first-session task.

Read this file fully before doing anything. Do not invent design choices that contradict it. When in doubt, ask before proceeding.

---

## 1. Mission (one sentence)

Build the open-source equivalent of Anthropic's *Dreaming* feature for any agent and any model: a scheduled background process that reads recent agent sessions, extracts patterns, and rewrites the agent's long-term memory so it stays high-signal as it grows.

---

## 2. Context and why this exists

On **May 6, 2026**, Anthropic announced **Dreaming** for Claude Managed Agents — a memory-consolidation pass that runs between agent sessions, surfaces recurring patterns and mistakes, and updates an agent's long-term memory accordingly. Harvey reported a roughly 6× lift in completion rates after using it for legal agents.

That capability is currently locked to Anthropic Managed Agents customers. Every team running open-source agent stacks (Aider, OpenHands, Continue, Cline) or local models in regulated environments is missing it. **OpenDream fills that gap.**

Existing OSS memory layers — Letta (formerly MemGPT) and mem0 — handle storage and retrieval (append memories, semantically search, inject into context). Neither does the *consolidation* pass: the scheduled offline step that extracts cross-session patterns and restructures memory. That is the empty slot. OpenDream is exactly that consolidation layer, designed to plug into any existing memory system or agent framework.

---

## 3. v0 scope

### In scope for v0
- Three-stage pipeline: **trace → reflect → consolidate**
- Three adapters via a polymorphic `Adapter` base class:
  - **`claude_code`** — flagship adapter, reads `~/.claude/projects/*.jsonl`
  - **`generic_jsonl`** — universal escape hatch (any project can emit this format and ingest)
  - **`aider`** — parses `.aider.chat.history.md`
- Storage: **SQLite + sqlite-vec**, single file
- LLM access: **dual-backend** — OpenAI-compatible (default; works with Ollama, vLLM, OpenAI, Together, Groq, Fireworks, anything OpenAI-compatible) and **Anthropic native** (selected via `OPENDREAM_LLM_PROVIDER=anthropic`)
- Static memory injection: export consolidated memory into **`AGENTS.md`** (the cross-framework standard adopted by Cursor, Codex, OpenAI agents, GitHub Copilot agent mode, 60K+ repos), wrapped in an idempotent delimited section so any existing `AGENTS.md` content is preserved
- CLI built with **Typer**
- Eval harness with 15 fixed coding tasks, baseline-vs-dreamed comparison
- Tests with **Pytest**

### Explicitly OUT of scope for v0
- OpenHands or other agent adapters (deferred to v0.5)
- MCP server for dynamic memory retrieval (v0.5)
- Web UI for reviewing dream diffs (v0.5)
- Multi-agent shared dreams (v1)
- Federated cross-organization dreaming (v1.5)
- Daemon, scheduler, cron integration (cron is two lines of docs, not a feature)
- LangChain, LlamaIndex, LiteLLM — do not pull these in

### v0 ships when all four are true
1. `pip install -e . && opendream init` works on a fresh machine.
2. Round-trip on Claude Code: ingest 20 real Claude Code sessions from `~/.claude/projects/`, run reflect, run dream, export memory into the project's `AGENTS.md` between the OpenDream markers, agent reads it on next session start.
3. Eval harness reports a measurable lift on the 15-task suite (baseline vs. dreamed agent, 5 trials each per task). Target ≥ 5 percentage points.
4. README polished + 60-second demo recorded + GitHub repo public + MIT license.

---

## 4. Architecture (three stages)

```
   Agent session (raw)
        │
        ▼
   ┌─────────┐    ┌──────────┐    ┌─────────────┐    ┌──────────┐
   │  TRACE  │───▶│  REFLECT │───▶│ CONSOLIDATE │───▶│  MEMORY  │
   └─────────┘    └──────────┘    └─────────────┘    └──────────┘
   adapter        per-session     cross-session       versioned
   ingests        structured      pattern             memory store
   raw history    observations    extraction          + diffable
```

- **Trace.** An adapter converts raw agent history (Claude Code `.jsonl`, Aider `.aider.chat.history.md`, or any project's own format via `generic_jsonl`) into a normalized `Session` object with messages, tool calls, and metadata. Adapters all subclass the `Adapter` base in `opendream/adapters/base.py`.
- **Reflect (Stage 1).** One LLM call per session produces a structured `Reflection`: what task, what approach, what worked, what failed, decision points, candidates for memory. The Stage 1 meta-prompt is embedded below.
- **Consolidate (Stage 2 — the "dream").** One LLM call per dream cycle takes N reflections + the current consolidated memory and proposes `MemoryUpdate`s (`add` / `modify` / `deprecate`). The Stage 2 meta-prompt is embedded below.
- **Memory.** A versioned store. Every dream cycle produces a diff. Rollback supported. Export to the project's `AGENTS.md` between idempotent markers (so existing `AGENTS.md` content is left untouched) for the agent to read.

**Reflect and Consolidate are two separate LLM calls. Do not fuse them.** Stage 1 runs per session; Stage 2 runs across many sessions. They have different cognitive jobs. Fusing them destroys the architecture.

---

## 5. Locked technical decisions

| Decision | Choice | Rationale |
|---|---|---|
| Python version | **3.11+** | Modern type syntax (`X \| None`), used throughout the data models |
| Data models | **Pydantic 2.x** | Validation + JSON serialization out of the box |
| Storage | **SQLite stdlib + sqlite-vec** | Single-file, zero ops, vector search included |
| LLM client | **dual-backend: `openai` SDK (default) + `anthropic` SDK (native)** | One client wraps both; provider chosen via `OPENDREAM_LLM_PROVIDER=openai\|anthropic`. The OpenAI SDK with a custom `base_url` covers Ollama, vLLM, Together, Groq, Fireworks, and OpenAI itself; the Anthropic SDK is used directly so we get prompt caching, thinking, and the latest Claude features without proxy contortions. |
| CLI | **Typer + Rich** | Modern ergonomics, good help text |
| Tests | **Pytest** | — |
| License | **MIT** | Maximum adoption |
| Memory injection | **`AGENTS.md` (cross-framework standard) with idempotent `<!-- OPENDREAM:BEGIN -->` / `<!-- OPENDREAM:END -->` section** | Debuggable, diffable, doesn't require any agent-framework changes, and is read natively by Cursor / Codex / OpenAI agents / GitHub Copilot agent mode / 60K+ repos. Claude Code users can opt in via `ln -s AGENTS.md CLAUDE.md`. |
| Dream trigger | **Manual CLI command** | No daemon, no scheduler |
| Reference adapter | **`claude_code`** (flagship) + **`generic_jsonl`** (escape hatch) + **`aider`** | The first reaches the largest installed base; the second lets any stack ingest by emitting a documented JSONL schema; the third is kept because it works and demonstrates a third real adapter against the abstract base. |

Total dependency count is seven (the seventh is `anthropic`). Keep it that way.

---

## 6. Final project structure

```
opendream/
├── pyproject.toml                       # exact contents in §10
├── README.md                            # write at end of v0
├── SPEC.md                              # this file
├── docs/
│   └── ADAPTERS.md                      # universal JSONL schema + custom-adapter template
├── opendream/
│   ├── __init__.py
│   ├── cli.py                           # Typer entry point
│   ├── trace.py                         # data models — exact contents in §11
│   ├── store.py                         # SQLite + sqlite-vec layer
│   ├── llm.py                           # dual-backend (OpenAI-compat + Anthropic native)
│   ├── reflect.py                       # Stage 1 logic
│   ├── consolidate.py                   # Stage 2 logic
│   ├── memory.py                        # apply updates + export AGENTS.md (idempotent)
│   ├── prompts/
│   │   ├── reflect.md                   # exact contents in §12
│   │   └── consolidate.md               # exact contents in §13
│   └── adapters/
│       ├── __init__.py
│       ├── base.py                      # abstract Adapter — see §15
│       ├── claude_code.py               # parse ~/.claude/projects/*.jsonl  (flagship)
│       ├── generic_jsonl.py             # universal escape hatch
│       └── aider.py                     # parse .aider.chat.history.md
├── tests/
│   ├── test_store.py
│   ├── test_adapters_base.py
│   ├── test_claude_code_adapter.py
│   ├── test_generic_jsonl_adapter.py
│   ├── test_aider_adapter.py
│   ├── test_reflect.py
│   └── test_consolidate.py
└── eval/
    ├── tasks/                           # 15 fixed coding tasks
    ├── runner.py                        # baseline vs dreamed
    └── README.md
```

---

## 7. CLI surface (v0 target)

```bash
opendream init                                       # init local config + db
opendream ingest <adapter> <path>                    # polymorphic; <adapter> ∈ claude_code | aider | generic_jsonl
opendream ingest <adapter> -                         # read from stdin
opendream sessions list                              # list ingested sessions
opendream reflect [--session-id ID]                  # run stage 1 on a session
opendream reflect --all-pending                      # reflect on every un-reflected session
opendream reflect ... [--max-message-chars N]        # cap each rendered msg body (compresses Write/Edit-heavy sessions)
opendream dream [--last N] [--review]                # run stage 2; --review opens diff in $EDITOR
opendream memory list                                # show current consolidated memory
opendream memory show <ID>                           # show one entry
opendream memory diff --since DATE                   # show how memory evolved
opendream memory export --format agents-md [--out F] # write/refresh AGENTS.md (idempotent section)
opendream eval run [--baseline | --dreamed]          # run benchmark
```

`opendream ingest` dispatches by adapter name; new adapters (subclass `opendream.adapters.base.Adapter`) become available the moment they register via `register_adapter`. Implement these incrementally — `init` and `ingest claude_code` first, the rest follows.

---

## 8. Build sequence

### Week 1 — close the loop end-to-end on Aider, no quality bar yet

- **Day 1–2.** Create the directory structure. Drop in `pyproject.toml`, `opendream/trace.py`, `opendream/prompts/reflect.md`, `opendream/prompts/consolidate.md` (all from this file). Implement `store.py` with SQLite + sqlite-vec schema matching the Pydantic models. Implement `adapters/aider.py` to parse `.aider.chat.history.md` into `Session`. Wire `opendream init` and `opendream ingest aider <path>` in `cli.py`. Goal: `init` creates the DB, `ingest` round-trips a real Aider session into SQLite cleanly.
- **Day 3–4.** Implement `llm.py` (dual-backend: OpenAI-compat with `base_url`, Anthropic native; selected via `OPENDREAM_LLM_PROVIDER`). Implement `reflect.py`: load `prompts/reflect.md`, format with session, call the LLM, parse JSON into `Reflection`, store. Run on real Claude Code sessions of your own. Tune the prompt until reflections parse reliably and observations look useful.
- **Day 5–7.** Implement `consolidate.py`: same shape but Stage 2. Implement `memory.py`: apply `MemoryUpdate`s, version, export to `AGENTS.md` between the idempotent OpenDream markers. Iterate the consolidate prompt — this is the hardest part. Run cycles on batches of 10–20 reflections. Eyeball outputs. Apply the test from the prompt itself: would this entry, read 3 months from now in a fresh session, actually change agent behavior? If not, the prompt is too vague.

### Week 2 — eval, polish, ship

- **Day 8–10.** Build `eval/`. Pick 15 small, realistic coding tasks with deterministic scoring (you can crib structure from Aider's polyglot benchmark). The runner spins up the agent with and without the `AGENTS.md` block injected, runs each task 5 times, reports success rates per condition.
- **Day 11.** Generate 30+ real agent sessions of your own work to feed the dreamer (Claude Code sessions are the easiest to harvest in bulk from `~/.claude/projects/`). Run several dream cycles. Watch memory grow and stabilize.
- **Day 12.** Run eval. Get the number. If lift ≥ 5 percentage points, proceed. Otherwise iterate prompts.
- **Day 13.** Write `README.md` properly (pitch + quickstart + the eval number). Record a 60-second demo (asciinema works). Pick the final repo name. MIT license.
- **Day 14.** Ship. Hacker News, r/LocalLLaMA, Aider Discord, ping the OpenHands team.

---

## 9. Key design opinions (do not casually override)

1. **Reflect and Consolidate are separate LLM calls.** Do not fuse them.
2. **Evidence is mandatory.** Every observation cites a session reference; every memory update cites reflection ids. No evidence = the entry is rejected.
3. **Memory must shrink as well as grow.** The consolidator is required to consider deprecation. A memory that only accumulates becomes noise.
4. **The "would this change behavior in 3 months" test** governs whether a memory entry is worth keeping. Vague entries fail this test.
5. **No daemon, no scheduler, no web UI in v0.** All triggers are CLI commands.
6. **Static memory injection via `AGENTS.md` (idempotent section).** No dynamic retrieval, no MCP server in v0. The exporter only ever rewrites the content between `<!-- OPENDREAM:BEGIN -->` and `<!-- OPENDREAM:END -->`; nothing else in the file is touched.
7. **The eval ships in v0.** The credibility of the project depends on a real before/after number. Do not defer the eval.
8. **Six dependencies, no more.** If a feature seems to require a seventh dependency, the feature is probably out of scope for v0.

---

## 10. Embedded file: `pyproject.toml`

Create this file at the repo root with exactly these contents:

```toml
[project]
name = "opendream"
version = "0.0.1"
description = "Memory consolidation for AI agents — works with any model, any framework."
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "Vincent Gomes" }]
keywords = ["ai", "agents", "memory", "llm", "claude-code", "aider", "openhands", "agents-md"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
]

dependencies = [
    "pydantic>=2.6",
    "openai>=1.30",
    "anthropic>=0.40",
    "sqlite-vec>=0.1.0",
    "typer>=0.12",
    "rich>=13.7",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.4",
    "mypy>=1.10",
]

[project.scripts]
opendream = "opendream.cli:app"

[project.urls]
Homepage = "https://github.com/YOURNAME/opendream"
Issues = "https://github.com/YOURNAME/opendream/issues"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## 11. Embedded file: `opendream/trace.py`

This is the schema for the entire pipeline. Every other module depends on these models. Create this file with exactly these contents and do not modify the schema without an explicit discussion:

```python
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
Valence = Literal["positive", "negative", "neutral"]
SessionCompleteness = Literal["completed", "interrupted", "errored", "partial"]


class BehaviorObservation(BaseModel):
    """A neutral observation of agent behavior (replaces what_worked/what_failed)."""
    observation: str
    evidence: str
    confidence: Confidence
    scope: Scope
    valence: Valence = "neutral"


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
    behaviors_observed: list[BehaviorObservation] = Field(default_factory=list)
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
    """Stage 1 output: one structured reflection per session.

    Schema v2: adds `session_completeness` + `reflection_confidence` (the v1
    prompt-tuning round surfaced cascade caps when these were absent), and
    splits classification into target (what was asked) vs observed (what the
    agent actually did) so the consolidator can spot divergence as signal.
    """
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    created_at: datetime = Field(default_factory=datetime.utcnow)
    session_completeness: SessionCompleteness
    reflection_confidence: Confidence
    target_task_classification: TaskClassification
    observed_work_classification: TaskClassification
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
```

---

## 12. Embedded file: `opendream/prompts/reflect.md`

This is the Stage 1 meta-prompt. The text inside is loaded at runtime, formatted with the session, and sent to the LLM. Create this file with exactly these contents:

**v2 (2026-05-07). v0 → v1 fixed 7 defects (forced decision_points, polarized what_worked/failed, ungated candidates, no completeness/confidence signals, no target-vs-observed split). v1 → v2 fixed 3 more after a real-output review on a substantive 638-message session: (1) the `session_completeness == "interrupted"` rule was too literal — an early `[Request interrupted by user]` followed by ~380 substantive messages was being mis-classified, cascading a `reflection_confidence` cap; (2) the `tool_use_notes` bar of "non-obvious" excluded standard-but-useful patterns another agent instance would benefit from; (3) the `valence` default was implicitly skewing positive (6/7 entries) — competence is `neutral`, not `positive`.**

````markdown
# Reflection prompt (Stage 1)

You are a meta-cognitive observer for an AI agent. You will be given a complete record of a single agent session: the task it was asked to do, the actions it took, the outcomes of those actions, and (when available) whether it ultimately succeeded.

Your job is to produce a structured reflection on this session that will later be combined with reflections from other sessions to identify cross-session patterns. Think of yourself as a researcher taking field notes — your job is to extract observations, not to give advice and not to summarize for a human reader.

## Principles

1. **Sparseness over completeness.** Empty arrays and minimal entries are the default. A reflection that force-fills every field with marginal content is worse than one that says little but says it well. The consolidator must spend tokens filtering noise, so noise is expensive. **If you would have to invent content to populate a field, don't.**

2. **Be skeptical of single-session conclusions.** Mark observations as low confidence unless you have clear in-session evidence (multiple instances, explicit user feedback, clear test outcomes).

3. **Distinguish task-specific from generalizable.** "The function `parseUser` had a bug" is task-specific noise. "The agent re-ran the same failing test 4 times before checking the test setup" is a generalizable pattern.

4. **Cite evidence.** Every observation references a specific moment — message index, tool call id, or short quote. Without evidence, an observation is speculation.

5. **No advice.** Do not propose fixes, improvements, or recommendations. The consolidator handles that across many reflections. Your job is to observe.

## Inputs

### Task description
{task_description}

### Session trace
{session_trace}

### Outcome (if known)
{outcome}

## Output

Return a single JSON object. No commentary, no markdown fences.

```json
{
  "session_completeness": "<completed | interrupted | errored | partial>",
  "reflection_confidence": "<low | medium | high>",
  "target_task_classification": {
    "type": "<bug_fix | feature_addition | refactor | exploration | debugging | test_writing | documentation | other>",
    "domain": "<short description, e.g. 'react frontend', 'spring boot api'>",
    "complexity": "<trivial | simple | moderate | complex>"
  },
  "observed_work_classification": {
    "type": "<same enum — what the agent ACTUALLY did>",
    "domain": "<as above>",
    "complexity": "<as above>"
  },
  "approach": {
    "strategy_summary": "<1-2 sentences on the agent's overall approach>",
    "tool_sequence": ["<ordered tools/actions used>"],
    "decision_points": []
  },
  "observations": {
    "behaviors_observed": [],
    "tool_use_notes": [],
    "context_observations": null
  },
  "outcome": {
    "completed": true | false | "unclear",
    "user_satisfied": true | false | "unclear",
    "evidence": "<what tells you this>"
  },
  "candidates_for_memory": []
}
```

## Field rules

**`session_completeness`** — observable from the trace itself.
- `completed` — task reached a natural end. **An early `[Request interrupted by user]` followed by sustained substantive work that reaches deliverables still counts as `completed`** — the interruption was a redirect, not a termination.
- `interrupted` — `[Request interrupted by user]` or equivalent appears **AND** the trace ends without resumed substantive work after the interruption. The interruption is the terminal event, not a mid-session redirect.
- `errored` — session ended due to a tool/system error.
- `partial` — trace ended mid-task without explicit interruption (truncated, abandoned).

**`reflection_confidence`** — your own confidence in this reflection as a whole.
- `high` — only when `session_completeness == "completed"` **and** the trace contains ≥ 50 messages of substantive interaction. Most reflections will not qualify.
- `medium` — substantive completed sessions below the bar, or long interrupted sessions where you saw enough to draw inferences.
- `low` — short sessions, interrupted before meaningful work, or sessions where the trace is too thin to support strong observations. **Default for sessions of <20 messages or any interruption inside the first quarter of the trace.**

**`target_task_classification`** — what the user *asked* for.
**`observed_work_classification`** — what the agent *actually did*.
These usually match. On interrupted or off-track sessions they diverge — that divergence is itself signal for the consolidator.

**`decision_points`** — include ONLY when the agent faced a non-obvious choice with multiple plausible options *visible in the trace*. **If you would have to invent the alternative, do not include the decision point.** Empty array is the expected default; most sessions have none.

**`behaviors_observed`** — neutral descriptions of what the agent did. Each entry:
```json
{
  "observation": "<specific thing>",
  "evidence": "<reference into the session>",
  "confidence": "low | medium | high",
  "scope": "task_specific | generalizable",
  "valence": "positive | negative | neutral"
}
```
Most observations are `neutral`. Use `positive` only when there is clear evidence the behavior succeeded (e.g. tests went green, user confirmed); `negative` only when there is clear evidence it failed. **Do not force a polarity to fill the slot.**

**Valence calibration check.** If you find yourself marking >70% of observations as `positive`, you are likely confusing *"agent did something competent"* with *positive valence* — competence is `neutral`. The neutral default exists so observations don't have to earn their place via valence.

**`tool_use_notes`** — include a note when the tool use exhibits a pattern that **another agent instance would benefit from being told about explicitly**, even if experienced developers consider it standard. The bar is *"would this be useful in a future session prompt"*, not *"is this novel"*. Paraphrase is still not a note: "The tool was used to inspect the directory" describes nothing actionable. Empty array is acceptable when nothing rises to that bar.

**`candidates_for_memory`** — gate strictly. Do NOT propose a candidate if it is any of:
- `task_specific` AND `kind == "fact"` (transient state, not stable memory)
- `confidence == "low"` AND `scope == "task_specific"` (the consolidator filters these anyway, producing them just wastes tokens)
- something the consolidator can derive trivially from the rest of the reflection (don't restate)

**If you would propose fewer than one candidate after this filter, return an empty array.** That is the correct outcome for thin or interrupted sessions.

Each candidate:
```json
{
  "kind": "pattern | failure_mode | workflow | preference | fact",
  "content": "<the actual claim, written so it would still make sense in 6 months>",
  "scope": "task_specific | generalizable",
  "evidence": "<reference into the session>",
  "confidence": "low | medium | high"
}
```

Return ONLY the JSON object. Empty arrays and `null` are valid wherever a field doesn't apply. Never invent evidence.
````

---

## 13. Embedded file: `opendream/prompts/consolidate.md`

This is the Stage 2 meta-prompt — the actual "dream" step. This is the most important piece of IP in the project. Create this file with exactly these contents:

````markdown
# Consolidation prompt (Stage 2 — the "dream" step)

You are the consolidator for an AI agent's long-term memory. You have access to:

1. The agent's **current consolidated memory** — entries already distilled from prior sessions.
2. A batch of **new reflections** — structured observations from recent agent sessions, each produced by the Stage 1 reflection pass.

Your job: propose a set of **updates** to the consolidated memory based on patterns visible across the new reflections, with reference to the existing memory. You do not take action — you propose updates that may be reviewed by a human or applied automatically depending on configuration.

## Principles (read carefully — these define what makes a good dream)

1. **Evidence over speculation.** Only propose updates supported by clear cross-session pattern evidence. Repetition matters: a pattern visible in a single reflection is rarely enough; a pattern visible in 5+ sessions across different tasks is real.

2. **Generalize cautiously.** Two reflections showing similar behavior may be a coincidence. Look for the same underlying *cause* expressed across different surface tasks. "The agent failed to handle null in 3 different ORMs" is generalizable. "The agent had bugs in 3 different files" is not.

3. **Deprecate, don't accumulate.** If new reflections contradict an existing memory entry, propose deprecation or modification. Memory must shrink as well as grow. A memory that only grows becomes noise. Be willing to throw things away.

4. **Be specific.** "Be careful with database queries" is useless. "When using `sqlx::query!` with optional joins, the agent has failed 4/5 times by forgetting NULL handling — should explicitly check the schema before writing the query" is useful. The test: would this entry, read 3 months from now in a fresh session, actually change the agent's behavior?

5. **Distinguish levels.**
   - **Workflows** — multi-step procedures that worked across multiple tasks.
   - **Patterns** — recurring observations about the environment or the agent's behavior.
   - **Failure modes** — recurring mistakes the agent has made.
   - **Preferences** — what this user, team, or codebase has shown they want.
   - **Facts** — stable truths about the environment.

6. **Show your reasoning.** Every update must cite which reflections support it. Every rejected candidate update goes in `non_updates` with a brief reason — this provides transparency and gives the next dream cycle visibility into what was previously considered.

## Inputs

### Current consolidated memory
{current_memory}

### New reflections
{new_reflections}

## Output

Return a single JSON object. No commentary, no markdown fences.

```json
{
  "summary": "<1 paragraph: what is most striking across these reflections, and how does it relate to existing memory>",
  "updates": [
    {
      "operation": "add | modify | deprecate",
      "kind": "workflow | pattern | failure_mode | preference | fact",
      "target_id": "<for modify/deprecate, the existing memory entry id; null for add>",
      "content": "<for add/modify, the new content — written specifically enough to change agent behavior>",
      "reason": "<1-3 sentences justifying this update>",
      "evidence": ["<reflection ids that support this>"],
      "confidence": "low | medium | high",
      "scope": "<what this applies to: a tool name, a task type, a file pattern, a codebase identifier, etc>"
    }
  ],
  "non_updates": [
    {
      "considered": "<the candidate update you considered>",
      "rejected_because": "<brief reason — insufficient evidence, contradicts higher-confidence existing entry, too task-specific, etc>"
    }
  ]
}
```

Return ONLY the JSON object. Empty arrays are fine. Never invent reflection ids or evidence — if you don't have support, propose nothing.
````

---

## 14. SQLite schema (for `opendream/store.py`)

When implementing `store.py`, the schema should mirror the Pydantic models in `trace.py`. Suggested tables:

- **`sessions`** — `id` (TEXT PK), `agent`, `project_id`, `started_at`, `ended_at`, `task_description`, `outcome_known`, `outcome_success`, `metadata` (JSON)
- **`messages`** — `session_id` (FK), `index`, `role`, `content`, `tool_name`, `tool_input` (JSON), `tool_output`, `timestamp`. Composite PK on `(session_id, index)`.
- **`reflections`** — `id` (TEXT PK), `session_id` (FK), `created_at`, plus a JSON column holding the rest of the `Reflection` (it's read whole, no need to shred). Add an index on `session_id`.
- **`memory_entries`** — `id` (TEXT PK), `kind`, `content`, `scope`, `confidence`, `created_at`, `last_reinforced_at`, `deprecated_at`, `deprecation_reason`, `evidence_reflection_ids` (JSON).
- **`memory_embeddings`** — sqlite-vec virtual table keyed on `memory_entries.id` for semantic retrieval over consolidated memory.
- **`dream_cycles`** — `id` (TEXT PK), `created_at`, `applied`, `applied_at`, plus a JSON column holding the rest.

Use TEXT for UUIDs, ISO-8601 strings for datetimes, JSON columns for nested structures that are read whole. Migrations are unnecessary for v0 — ship one schema and only change it via an explicit version bump later.

---

## 15. Adapter architecture & notes

All adapters subclass `opendream.adapters.base.Adapter`:

```python
class Adapter(ABC):
    name: str

    @abstractmethod
    def discover_sessions(self, root: Path) -> list[Path]: ...

    @abstractmethod
    def parse_sessions(self, path: Path) -> list[Session]: ...
```

Note the divergence from a strict singular `parse_session(path) -> Session`: real history formats often pack many sessions into one file (`.aider.chat.history.md` and the `generic_jsonl` escape hatch both do), so the contract returns a list. For 1-file-1-session adapters like `claude_code`, the list has length 1.

Adapters register themselves with `register_adapter(MyAdapter)` so the CLI's polymorphic dispatch (`opendream ingest <name> <path>`) finds them.

### `claude_code` adapter (flagship)

Source: `~/.claude/projects/<project-slug>/<session-uuid>.jsonl`. Each `.jsonl` is **one session**. Each line is a JSON event with a `type` field; v0 extracts only `user` and `assistant` events. User content is a string; assistant content is a list of blocks (`text` / `thinking` / `tool_use`) — concatenate text blocks into the message body and inline tool calls as readable annotations. Use `cwd` and `gitBranch` to populate `project_id` and metadata, and the first event's `timestamp` for `started_at`.

`discover_sessions(root)` walks the root recursively for `*.jsonl` files. Tolerate malformed lines.

### `generic_jsonl` adapter (universal escape hatch)

The lingua franca that lets any project — regardless of agent framework — emit data we can ingest. **One Session per line**, where each line is a JSON document conforming to the `Session` schema in `trace.py`. A file may hold any number of sessions.

Schema and a 50-line custom-adapter template live in `docs/ADAPTERS.md`. The full target for v0 is: any team can write a custom emitter for their stack in under 50 lines and immediately get the OpenDream pipeline.

### `aider` adapter

`.aider.chat.history.md` at the project root. Real-world format (slightly tighter than what older versions of this spec said):
- A line matching `# aider chat started at <timestamp>` opens a session.
- One or more consecutive lines prefixed with `#### ` form a single user message.
- Whatever non-`####` content follows — until the next `####` block or session banner — is the assistant's reply, including inline tool/edit fences.
- Tool calls stay embedded in `content` as raw text for v0; structured extraction is a v0.5 improvement.

Be tolerant: real history files are messy. Skip malformed sections rather than crashing.

### `Session.agent` field

Set to the adapter's `name` ("claude_code" / "generic_jsonl" / "aider"), so reflections and dreams can later filter or weight by source.

---

## 16. First session task — what to do RIGHT NOW

This is your bounded mission for session 1. Do not exceed it.

1. Confirm you have read this entire file. If anything contradicts itself or seems wrong, ask before proceeding.
2. Create the directory structure listed in §6, with empty `__init__.py` files where needed.
3. Create `pyproject.toml` with the exact contents from §10.
4. Create `opendream/trace.py` with the exact contents from §11.
5. Create `opendream/prompts/reflect.md` with the exact contents from §12.
6. Create `opendream/prompts/consolidate.md` with the exact contents from §13.
7. Implement `opendream/store.py` with the SQLite schema described in §14. Provide functions: `init_db(path)`, `save_session(session)`, `load_session(id)`, `list_sessions()`, plus stubs (raise `NotImplementedError`) for reflection/memory/dream methods you'll fill in later.
8. Implement `opendream/adapters/base.py` with the `Adapter` ABC from §15 and a tiny `register_adapter` / `get_adapter` registry. Add a stub `claude_code` adapter (subclass exists, methods raise `NotImplementedError`) so the registry has at least one entry.
9. Implement `opendream/cli.py` with a Typer `app`. Wire two commands for now: `init` (creates the SQLite database at `~/.opendream/db.sqlite` by default, configurable via `--path`) and a stub `ingest <adapter> <path>` that looks the adapter up in the registry and prints `"not implemented yet"`.
10. Memory injection: `memory.py` writes to **`AGENTS.md`** between `<!-- OPENDREAM:BEGIN -->` and `<!-- OPENDREAM:END -->`. The exporter must (a) create the file with the markers if it doesn't exist, (b) replace only the content between markers if the file exists with markers, (c) append a marked block at the end if the file exists without markers. Never destroy unmarked content. (Stub OK in session 1; full impl in session 2.)
11. Run `pip install -e .` in the repo. Run `opendream init`. Verify the database file exists and the schema is correct.
12. Commit with message `chore: scaffold opendream v0 — data models, prompts, store, adapter base, cli init`.

**Do not** in this first session:
- Implement any adapter's `parse_sessions` body (claude_code / generic_jsonl / aider all stay stubs)
- Implement reflect, consolidate, or memory logic
- Write any LLM client code
- Build the eval harness
- Write tests beyond a smoke test that `init_db` creates tables and the adapter registry returns a stub

Stop when `opendream init` works on a fresh machine and the database has the expected tables. That is the end of session 1. Commit. Then start session 2 with the `claude_code` adapter as the next focus.
