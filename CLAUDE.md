# OpenDream — full specification for Claude Code

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
- One reference adapter: **Aider** (parses `.aider.chat.history.md`)
- Storage: **SQLite + sqlite-vec**, single file
- LLM access: **OpenAI Python SDK** with configurable `base_url` (works with Ollama, vLLM, OpenAI, Anthropic via proxy, Together, Groq, Fireworks, anything OpenAI-compatible)
- Static memory injection: export consolidated memory as `OPENDREAM.md` for the agent to read at session start
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
2. Round-trip on Aider: ingest 20 real Aider sessions, run reflect, run dream, export memory to `OPENDREAM.md`, agent reads it on next session start.
3. Eval harness reports a measurable lift on the 15-task suite (baseline vs. dreamed Aider, 5 trials each per task). Target ≥ 5 percentage points.
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

- **Trace.** An adapter converts raw agent history (e.g., `.aider.chat.history.md`) into a normalized `Session` object with messages, tool calls, and metadata.
- **Reflect (Stage 1).** One LLM call per session produces a structured `Reflection`: what task, what approach, what worked, what failed, decision points, candidates for memory. The Stage 1 meta-prompt is embedded below.
- **Consolidate (Stage 2 — the "dream").** One LLM call per dream cycle takes N reflections + the current consolidated memory and proposes `MemoryUpdate`s (`add` / `modify` / `deprecate`). The Stage 2 meta-prompt is embedded below.
- **Memory.** A versioned store. Every dream cycle produces a diff. Rollback supported. Export to `OPENDREAM.md` for the agent to read.

**Reflect and Consolidate are two separate LLM calls. Do not fuse them.** Stage 1 runs per session; Stage 2 runs across many sessions. They have different cognitive jobs. Fusing them destroys the architecture.

---

## 5. Locked technical decisions

| Decision | Choice | Rationale |
|---|---|---|
| Python version | **3.11+** | Modern type syntax (`X \| None`), used throughout the data models |
| Data models | **Pydantic 2.x** | Validation + JSON serialization out of the box |
| Storage | **SQLite stdlib + sqlite-vec** | Single-file, zero ops, vector search included |
| LLM client | **`openai` SDK with custom `base_url`** | One client supports Ollama, vLLM, OpenAI, Anthropic, etc. |
| CLI | **Typer + Rich** | Modern ergonomics, good help text |
| Tests | **Pytest** | — |
| License | **MIT** | Maximum adoption |
| Memory injection | **Static `OPENDREAM.md`** | Debuggable, diffable, no agent-framework changes required |
| Dream trigger | **Manual CLI command** | No daemon, no scheduler |
| Agent adapter (v0) | **Aider** | Cleanest session boundaries, structured chat history, large user base |

Total dependency count is six. Keep it that way.

---

## 6. Final project structure

```
opendream/
├── pyproject.toml                       # exact contents in §10
├── README.md                            # write at end of v0
├── CLAUDE.md                            # this file
├── opendream/
│   ├── __init__.py
│   ├── cli.py                           # Typer entry point
│   ├── trace.py                         # data models — exact contents in §11
│   ├── store.py                         # SQLite + sqlite-vec layer
│   ├── llm.py                           # OpenAI-compat client wrapper
│   ├── reflect.py                       # Stage 1 logic
│   ├── consolidate.py                   # Stage 2 logic
│   ├── memory.py                        # apply updates + export OPENDREAM.md
│   ├── prompts/
│   │   ├── reflect.md                   # exact contents in §12
│   │   └── consolidate.md               # exact contents in §13
│   └── adapters/
│       ├── __init__.py
│       └── aider.py                     # parse .aider.chat.history.md
├── tests/
│   ├── test_store.py
│   ├── test_aider_adapter.py
│   ├── test_reflect.py
│   └── test_consolidate.py
└── eval/
    ├── tasks/                           # 15 fixed Aider tasks
    ├── runner.py                        # baseline vs dreamed
    └── README.md
```

---

## 7. CLI surface (v0 target)

```bash
opendream init                              # init local config + db
opendream ingest aider <path>               # ingest an aider session
opendream ingest --stdin                    # ingest from stdin
opendream sessions list                     # list ingested sessions
opendream reflect [--session-id ID]         # run stage 1 on a session
opendream reflect --all-pending             # reflect on every un-reflected session
opendream dream [--last N] [--review]       # run stage 2; --review opens diff in $EDITOR
opendream memory list                       # show current consolidated memory
opendream memory show <ID>                  # show one entry
opendream memory diff --since DATE          # show how memory evolved
opendream memory export --format aider      # write OPENDREAM.md
opendream eval run [--baseline | --dreamed] # run benchmark
```

Implement these incrementally — `init` and `ingest aider` first, the rest follows.

---

## 8. Build sequence

### Week 1 — close the loop end-to-end on Aider, no quality bar yet

- **Day 1–2.** Create the directory structure. Drop in `pyproject.toml`, `opendream/trace.py`, `opendream/prompts/reflect.md`, `opendream/prompts/consolidate.md` (all from this file). Implement `store.py` with SQLite + sqlite-vec schema matching the Pydantic models. Implement `adapters/aider.py` to parse `.aider.chat.history.md` into `Session`. Wire `opendream init` and `opendream ingest aider <path>` in `cli.py`. Goal: `init` creates the DB, `ingest` round-trips a real Aider session into SQLite cleanly.
- **Day 3–4.** Implement `llm.py` (thin OpenAI-compat wrapper, configurable `base_url`). Implement `reflect.py`: load `prompts/reflect.md`, format with session, call the LLM, parse JSON into `Reflection`, store. Run on real Aider sessions of your own. Tune the prompt until reflections parse reliably and observations look useful.
- **Day 5–7.** Implement `consolidate.py`: same shape but Stage 2. Implement `memory.py`: apply `MemoryUpdate`s, version, export `OPENDREAM.md`. Iterate the consolidate prompt — this is the hardest part. Run cycles on batches of 10–20 reflections. Eyeball outputs. Apply the test from the prompt itself: would this entry, read 3 months from now in a fresh session, actually change agent behavior? If not, the prompt is too vague.

### Week 2 — eval, polish, ship

- **Day 8–10.** Build `eval/`. Pick 15 small, realistic Aider tasks with deterministic scoring (you can crib structure from Aider's polyglot benchmark). The runner spins up Aider with and without `OPENDREAM.md` injected, runs each task 5 times, reports success rates per condition.
- **Day 11.** Generate 30+ real Aider sessions of your own work to feed the dreamer. Run several dream cycles. Watch memory grow and stabilize.
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
6. **Static memory injection via `OPENDREAM.md`.** No dynamic retrieval, no MCP server in v0.
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
keywords = ["ai", "agents", "memory", "llm", "aider", "openhands"]
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
```

---

## 12. Embedded file: `opendream/prompts/reflect.md`

This is the Stage 1 meta-prompt. The text inside is loaded at runtime, formatted with the session, and sent to the LLM. Create this file with exactly these contents:

````markdown
# Reflection prompt (Stage 1)

You are a meta-cognitive observer for an AI agent. You will be given a complete record of a single agent session: the task it was asked to do, the actions it took, the outcomes of those actions, and (when available) whether it ultimately succeeded.

Your job is to produce a structured reflection on this session that will later be combined with reflections from other sessions to identify cross-session patterns. Think of yourself as a researcher taking field notes — your job is to extract observations, not to give advice and not to summarize for a human reader.

## Principles

1. **Be skeptical of single-session conclusions.** Mark observations as low confidence unless you have clear in-session evidence (multiple instances within the session, explicit user feedback, clear test outcomes).
2. **Distinguish task-specific from generalizable.** "The function `parseUser` had a bug" is task-specific noise. "The agent re-ran the same failing test 4 times before checking the test setup" is a generalizable pattern.
3. **Record decision points, not just outcomes.** Where did the agent face multiple plausible options? What did it choose? What else was visible? Future memory updates depend on this.
4. **Cite evidence.** Every observation must reference specific moments in the session — message indices, tool call identifiers, or short quotes. Without evidence, an observation is speculation.
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
  "task_classification": {
    "type": "<bug_fix | feature_addition | refactor | exploration | debugging | test_writing | documentation | other>",
    "domain": "<short description, e.g. 'react frontend', 'spring boot api', 'postgres migration'>",
    "complexity": "<trivial | simple | moderate | complex>"
  },
  "approach": {
    "strategy_summary": "<1-2 sentences on the agent's overall approach>",
    "tool_sequence": ["<ordered names of tools/actions used, e.g. 'read_file', 'edit_file', 'run_tests'>"],
    "decision_points": [
      {
        "moment": "<what was being decided>",
        "choice_made": "<what the agent did>",
        "alternatives_visible": "<what else was on the table, if anything>",
        "evidence": "<message index or short quote>"
      }
    ]
  },
  "observations": {
    "what_worked": [
      {
        "observation": "<specific thing>",
        "evidence": "<reference into the session>",
        "confidence": "low | medium | high",
        "scope": "task_specific | generalizable"
      }
    ],
    "what_failed": [
      {
        "observation": "<specific thing>",
        "evidence": "<reference>",
        "confidence": "low | medium | high",
        "scope": "task_specific | generalizable"
      }
    ],
    "tool_use_notes": [
      {
        "tool": "<tool name>",
        "note": "<how it was used; effective patterns; mistake patterns>",
        "evidence": "<reference>"
      }
    ],
    "context_observations": "<anything about the codebase, the user's preferences, or the environment that seems persistently relevant beyond this session>"
  },
  "outcome": {
    "completed": true | false | "unclear",
    "user_satisfied": true | false | "unclear",
    "evidence": "<what tells you this — explicit user statement, test pass/fail, etc>"
  },
  "candidates_for_memory": [
    {
      "kind": "pattern | failure_mode | workflow | preference | fact",
      "content": "<the actual claim or rule, written so it would still make sense in 6 months>",
      "scope": "task_specific | generalizable",
      "evidence": "<reference into the session>",
      "confidence": "low | medium | high"
    }
  ]
}
```

Return ONLY the JSON object. If a field doesn't apply, use `null` or an empty array. Never invent evidence.
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

## 15. Aider adapter notes (for `opendream/adapters/aider.py`)

Aider chat history lives in `.aider.chat.history.md` at the project root. Format is markdown with conventions:

- `#### user` headers separate user turns
- `#### assistant` headers separate assistant turns
- Tool calls and file edits are inline, often as fenced code blocks
- A new session is delimited by a top-level header line of dashes or by the file being recreated

For v0, the parser only needs to:
1. Split the file into sessions (best heuristic: look for the Aider session-start banner pattern).
2. Within each session, split into messages by `#### user` / `#### assistant` headers.
3. Convert each into a `Message` with `index`, `role`, `content`. Tool calls can stay embedded in `content` as raw text for v0 — structured extraction is a v0.5 improvement.
4. Build a `Session` with `agent="aider"`, `started_at` from file modification time or first message timestamp if available.

Be tolerant: real Aider history files are messy. Skip malformed sections rather than crashing.

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
8. Implement `opendream/cli.py` with a Typer `app`. Wire two commands for now: `init` (creates the SQLite database at `~/.opendream/db.sqlite` by default, configurable via `--path`) and a stub `ingest aider <path>` that just prints `"not implemented yet"`.
9. Run `pip install -e .` in the repo. Run `opendream init`. Verify the database file exists and the schema is correct.
10. Commit with message `chore: scaffold opendream v0 — data models, prompts, store, cli init`.

**Do not** in this first session:
- Implement the Aider adapter beyond a stub
- Implement reflect, consolidate, or memory logic
- Write any LLM client code
- Build the eval harness
- Write tests beyond a smoke test that `init_db` creates tables

Stop when `opendream init` works on a fresh machine and the database has the expected tables. That is the end of session 1. Commit. Then start session 2 with the Aider adapter as the next focus.
