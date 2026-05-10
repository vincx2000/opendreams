# OpenDream

**Memory consolidation for AI agents — works with any model, any framework.**

[![CI](https://github.com/vincx2000/opendreams/actions/workflows/ci.yml/badge.svg)](https://github.com/vincx2000/opendreams/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](pyproject.toml)
[![Status](https://img.shields.io/badge/status-v0--alpha-orange.svg)](#roadmap)

Anthropic's *Dreaming* (announced May 6, 2026; now in research preview for
Claude Managed Agents) is a memory-consolidation pass that runs between
agent sessions, surfaces recurring patterns and mistakes, and updates the
agent's long-term memory.

OpenDream brings that pass to any agent stack and any model: record sessions
in one tool (Claude Code, Aider) and the consolidated memory is read
natively by the next (Cursor, Codex, OpenHands, Copilot) via `AGENTS.md`.
The OSS memory-consolidation space crystallized rapidly in May 2026 — see
[How does this compare?](#how-does-this-compare) for the landscape and
where OpenDream actually fits.

### v0.0.2 eval result (2026-05-10) — domain-matched two-pass

OpenDream was measured on a 15-task fixed suite, 5 trials per task per
condition (150 trials total) under the
[two-pass design](eval/README.md#two-pass-mode-v002): pass-1 collects
baseline transcripts on the task suite, OpenDream consolidates *those*
into an `AGENTS.md`, pass-2 re-runs the suite dreamed against that
AGENTS.md. This isolates the consolidation pass on the codebase it's
actually being asked to learn.

| | Baseline | Dreamed | Δ |
|---|---:|---:|---:|
| **Aggregate (15 tasks)** | **92%** | **96%** | **+4.0pp** |
| `07_bulk_create_members` (feature) | 40% | 60% | **+20.0** |
| `12_generic_repository_base` (refactor) | 80% | 100% | **+20.0** |
| `14_test_translate_function` (test addition) | 80% | 100% | **+20.0** |
| Other 12 tasks | 100%/80% | 100%/80% | 0 (mostly ceiling) |

**The +4.0pp aggregate misses SPEC §3's ≥5pp target by 1pp.** Honest
reading: the consolidator is doing its job — it produces +20pp lifts on
the three tasks where there's room to lift, and zero regressions
anywhere — but **12 of 15 tasks are ceiling-effected at 100% baseline**,
so the aggregate can't clear 5pp without a more discriminating suite.
That's a v0.0.3 task (replace the ceiling-effected tasks with harder
discriminators), not a v0.0.2 task.

What changed from v0.0.1-alpha (cross-domain): both regressions are gone.
Task 7 went from **−20pp** to **+20pp**, task 9 from **−20pp** to 0pp. The
"off-domain memory distracts the agent" thesis from v0.0.1's CHANGELOG is
confirmed and fixed; consolidated memory derived from this codebase's own
runs strictly improves or holds steady, never regresses. See
[`CHANGELOG.md`](CHANGELOG.md) `[0.0.2]` for the per-task delta and the
cost breakdown.

## What it does

```
   Agent session (raw)
        │
        ▼
   ┌─────────┐    ┌──────────┐    ┌─────────────┐    ┌──────────┐
   │  TRACE  │───▶│  REFLECT │───▶│ CONSOLIDATE │───▶│  MEMORY  │
   └─────────┘    └──────────┘    └─────────────┘    └──────────┘
   adapter        per-session     cross-session       AGENTS.md
   ingests        observations    pattern             (idempotent
   raw history    (Stage 1 LLM)   extraction          section)
                                  (Stage 2 LLM)
```

- **Trace.** An adapter normalizes your agent's raw history into a `Session`.
  Three adapters ship in v0:
  - `claude_code` — reads `~/.claude/projects/*.jsonl` (flagship)
  - `aider` — reads `.aider.chat.history.md`
  - `generic_jsonl` — universal escape hatch (any project can emit this)
- **Reflect (Stage 1).** One LLM call per session produces a structured
  `Reflection`: what task, what worked, what failed, decision points,
  candidates for memory.
- **Consolidate (Stage 2 — the "dream").** One LLM call per cycle takes N
  reflections + the current consolidated memory, and proposes
  add / modify / deprecate updates.
- **Memory.** A versioned store. Every dream produces a diff. Export to
  `AGENTS.md` between idempotent OpenDream markers — your agent reads it on
  the next session.

## Quickstart

### 1. Pick your adapter

| Your agent / tool | Adapter | Where its history lives |
|---|---|---|
| Claude Code | `claude_code` | `~/.claude/projects/<id>/*.jsonl` — find `<id>` with `ls ~/.claude/projects/` |
| Aider | `aider` | `<repo>/.aider.chat.history.md` |
| Cursor, Codex, Copilot, OpenHands, Continue, anything else | `generic_jsonl` | you emit it — see [`docs/ADAPTERS.md`](docs/ADAPTERS.md) |

### 2. Install + run

```bash
git clone https://github.com/vincx2000/opendreams && cd opendreams
pip install -e .
opendream init

# Pick the line that matches your adapter from step 1:
opendream ingest claude_code   ~/.claude/projects/<your-project>/
opendream ingest aider         path/to/.aider.chat.history.md
opendream ingest generic_jsonl path/to/sessions.jsonl

opendream reflect --all-pending && opendream dream && opendream memory export
```

Assumes `OPENAI_API_KEY` is exported. Other backends work too — set
`OPENDREAM_LLM_PROVIDER=anthropic` with `ANTHROPIC_API_KEY`, or point at any
OpenAI-compatible local model (Ollama, vLLM, Together, Groq, Fireworks); see
[LLM backend](#llm-backend) for the full env-var table.

Your project now has an `AGENTS.md` with consolidated memory between
`<!-- OPENDREAM:BEGIN -->` / `<!-- OPENDREAM:END -->` markers. Cursor, Codex,
OpenAI Agents, OpenHands, Continue, and Copilot agent mode read it natively.
Claude Code users: `ln -s AGENTS.md CLAUDE.md` and you're done.

## How does this compare?

The OSS memory-consolidation space went from "empty" to "crowded" in early
May 2026. Honest read of where OpenDream sits:

|  | Cross-framework | Consolidation pass | BYO LLM | Published eval | License |
|---|:-:|:-:|:-:|:-:|---|
| Anthropic *Dreaming* (Managed Agents) | Claude only | ✓ | Anthropic only | Harvey 6× completion | closed, paid |
| Claude Code Auto Dream / [dream-skill](https://github.com/grandamenium/dream-skill) | Claude Code only | ✓ | mostly Anthropic | — | various OSS |
| [OpenClawDreams](https://github.com/RogueCtrl/OpenClawDreams) | OpenClaw only | ✓ | ✓ | — | OSS |
| [mem0](https://github.com/mem0ai/mem0) | library-level | single-pass extract | ✓ | LoCoMo benchmarks | Apache 2.0 |
| [Letta](https://github.com/letta-ai/letta) | library-level | memory blocks | ✓ | filesystem benchmark | Apache 2.0 |
| [memsearch](https://github.com/zilliztech/memsearch) | ✓ | retrieval-focused | ✓ | — | OSS |
| **OpenDream** | **✓ (record-anywhere → AGENTS.md)** | **✓ (offline rewrite, evidence-tracked)** | **✓** | **+4.0pp two-pass** | **MIT** |

### Where OpenDream is sharper

- **Truly cross-framework.** Most consolidators are tied to a specific stack
  (Claude Code, OpenClaw) or are libraries you embed (mem0, Letta).
  OpenDream sits between adapters and `AGENTS.md` — record once, output is
  consumed by the entire `AGENTS.md`-reading ecosystem (Cursor, Codex,
  OpenAI agents, GitHub Copilot agent mode, 60K+ repos).
- **Eval rigor.** v0.0.1-alpha shipped a cross-domain eval that surfaced a
  −20pp regression on two tasks ("off-domain memory distracts the agent");
  v0.0.2 fixed it with a domain-matched two-pass methodology and showed
  +4.0pp aggregate, +20pp on three discriminating tasks, **zero
  regressions**. Most adjacent projects ship without published lift numbers.
- **No SaaS, no telemetry, no provider lock.** Sessions never leave your
  machine unless you point at a hosted LLM. Dual-backend client supports
  OpenAI-compatible (default; covers OpenAI, Ollama, vLLM, Together, Groq,
  Fireworks) and Anthropic native.

### Where OpenDream is currently weaker

- **No dynamic retrieval yet.** v0 writes static `AGENTS.md`; semantic
  retrieval lands in v0.5 (MCP server). For rich query semantics today,
  pair with mem0 or Letta — they're complementary.
- **Smaller adapter coverage.** Three first-party adapters (Claude Code,
  Aider, generic JSONL); OpenClaw and Letta have richer first-party
  ecosystems.
- **Smaller community.** Younger project; user base is much smaller than
  mem0's (40K+ stars) or Letta's.

### Picking the right tool

- Need rich graph-based retrieval today → **mem0**.
- Need stateful long-running agents → **Letta**.
- Need a turnkey Claude-Code-only dream cycle → **dream-skill** or **Auto Dream**.
- Need cross-framework portability with a published eval methodology → **OpenDream**.

## Memory injection: AGENTS.md

OpenDream writes consolidated memory into your project's `AGENTS.md` between
two markers:

```markdown
<!-- OPENDREAM:BEGIN -->
…consolidated memory…
<!-- OPENDREAM:END -->
```

`AGENTS.md` is the cross-framework standard read natively by Cursor, Codex,
OpenAI agents, GitHub Copilot agent mode, and 60K+ repos. The exporter only
ever rewrites the content between the markers, so any other content in
`AGENTS.md` is preserved.

### Claude Code users

Claude Code reads `CLAUDE.md`, not `AGENTS.md`. Symlink them:

```bash
ln -s AGENTS.md CLAUDE.md
```

Now Claude Code, Cursor, Codex, and Copilot all see the same consolidated
memory.

## LLM backend

Dual-backend client. Provider-agnostic from your code's perspective.

```bash
# Anthropic native (recommended for the dream step):
export OPENDREAM_LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=...

# Or OpenAI-compatible (works with OpenAI, Ollama, vLLM, Together, Groq, …):
export OPENDREAM_LLM_PROVIDER=openai     # default
export OPENAI_API_KEY=...
export OPENDREAM_LLM_BASE_URL=...        # only for non-OpenAI endpoints
```

### Env-var reference

| Variable | Default | Purpose |
|---|---|---|
| `OPENDREAM_LLM_PROVIDER` | `openai` | `openai` or `anthropic` |
| `OPENDREAM_REFLECT_MODEL` | `gpt-4o-mini` (OpenAI) / `claude-haiku-4-5-20251001` (Anthropic) | Stage 1 — cheap, runs per session |
| `OPENDREAM_DREAM_MODEL`   | `gpt-4o` (OpenAI) / `claude-sonnet-4-6` (Anthropic)         | Stage 2 — quality, runs per cycle |
| `OPENDREAM_LLM_BASE_URL`  | OpenAI's endpoint | Only set for Ollama / vLLM / Together / Groq / Fireworks |
| `OPENDREAM_LLM_API_KEY`   | falls back to `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Shared override |

Reflect (Stage 1) and Dream (Stage 2) have opposite cost/quality profiles, so
they get separate model selectors.

## Plugging in your stack

If your agent framework isn't covered by the three v0 adapters, write your
own. Subclass `Adapter`, decorate with `@register_adapter`, ~50 lines.

See [`docs/ADAPTERS.md`](docs/ADAPTERS.md) for the universal `generic_jsonl`
schema and a custom-adapter template.

## Prompt-tuning loop

The two pipeline meta-prompts (`opendream/prompts/reflect.md` and
`consolidate.md`) are deliberately editable. To tune them against your real
sessions without burning tokens:

```bash
# Render the prompt that would be sent for a session, no LLM call:
opendream reflect --dry-run --session-id <id>
# → /tmp/od_dryrun/reflect_<id>.txt

# Iterate on prompts/reflect.md, then either run the LLM normally:
opendream reflect --session-id <id> --show-json

# …or hand-author the JSON in your tool of choice and import:
cat reflection.json | opendream reflect --import-json --session-id <id>
```

Same `--dry-run` / `--import-json` / `--from` triple on `opendream dream`.

For sessions where Write/Edit tool calls embed full file contents (typical
Claude Code sessions can balloon to 165K+ tokens), use
`--max-message-chars 1000` to compress the rendered prompt before reflect.

## What's stored where?

| | |
|---|---|
| `~/.opendream/db.sqlite` | Sessions, reflections, dream cycles (one SQLite file) |
| `<your project>/AGENTS.md` | Consolidated memory, between OpenDream markers |
| Anywhere else | Nothing — sessions never leave your machine unless you point at a hosted LLM |

`chmod 600 ~/.opendream/db.sqlite` if your home directory is shared.

## v0 status

This is v0. The full spec lives in [`SPEC.md`](SPEC.md). What's done:

- [x] Three-stage pipeline (trace → reflect → consolidate → memory)
- [x] Three adapters (claude_code, aider, generic_jsonl) on a polymorphic base
- [x] AGENTS.md export with idempotent markers
- [x] Dual-backend LLM client (OpenAI-compat + Anthropic native)
- [x] Eval harness with FastAPI fixture suite (15 tasks)
- [x] CI: ruff + mypy + pytest on Python 3.11 + 3.12
- [x] Cross-domain eval (v0.0.1-alpha): +0.0pp aggregate, two regressions
      surfaced the cross-project memory-pollution problem
- [x] **Domain-matched two-pass eval (v0.0.2): +4.0pp aggregate, no
      regressions, three +20pp per-task lifts** — see eval result above
- [ ] Discriminating eval suite (v0.0.3 — replace 12 ceiling-effected tasks
      with harder discriminators so SPEC §3's ≥5pp aggregate target is reachable)
- [ ] 60-second demo (asciinema)
- [x] v0.0.2 shipped

## Known limitations

- **Cross-project memory pollution is measurable** (v0.0.1-alpha finding,
  fixed in v0.0.2). When consolidated memory comes from a different codebase
  than the agent works on, the cross-domain eval showed −20pp regressions on
  two feature tasks. v0.0.2's domain-matched two-pass eval eliminates those
  regressions. Until v0.5's MCP retrieval lands (semantic, project-scoped),
  **keep `~/.opendream/db.sqlite` scoped to a single codebase per machine**,
  or run `opendream init --path <project>/.opendream/db.sqlite` per project
  so memory pools don't bleed across domains.
- **The eval suite is ceiling-effected** (v0.0.2 finding). 12 of 15 tasks
  hit 100% baseline — the agent already crushes them without memory help,
  so the consolidator has no room to lift them. v0.0.2's +4.0pp aggregate
  missed SPEC §3's ≥5pp target by 1pp because of this dilution. v0.0.3
  will replace the ceiling-effected tasks with harder discriminators (e.g.,
  multi-step refactors, ambiguous bug fixes, cross-module feature additions).
- **No PyPI package yet.** Install from source via `pip install -e .` inside
  a clone. PyPI lands once v0.0.3 ships the discriminating eval.
- **No dynamic memory retrieval.** v0 only writes static `AGENTS.md`. MCP
  server lands in v0.5.
- **Aider tool-use blocks stay inlined as raw markdown** rather than getting
  parsed into `Message.tool_input`. Structured extraction is a v0.5 improvement.
- **The OSS memory-consolidation space is now crowded.** OpenDream is one of
  several active projects in this category as of May 2026 (see
  [How does this compare?](#how-does-this-compare)). The differentiation is
  cross-framework portability, eval rigor, and BYO-LLM openness — not
  uniqueness of the consolidation pass itself. If those three properties
  aren't load-bearing for your use case, an adjacent project may fit better.

## Roadmap

- **v0.0.3** — Discriminating eval suite (replace the 12 ceiling-effected
  tasks with harder discriminators so the aggregate lift number is
  unambiguous). PyPI release.
- **v0.5** — MCP server for dynamic memory retrieval (replaces static
  `AGENTS.md` injection for users with large memory pools); structured
  tool-call extraction (currently inlined as `<tool_use name="X">…</tool_use>`
  markers).
- **v1.0** — Stable cross-framework consolidator: dynamic retrieval shipped,
  head-to-head benchmarks against the field (mem0, Letta, dream-skill),
  schema migration tooling, stable Adapter API contract for third-party
  adapters. v1 is "the static + dynamic memory product is fully delivered
  and credible against the field," not a feature stretch.
- **v2.0** — Multi-agent shared dreams; federated cross-organization
  dreaming. (Originally v1.0 in `SPEC.md`; deferred as the OSS landscape
  matured around the single-agent case in May 2026.)

No promises, no dates. The
[issues](https://github.com/vincx2000/opendreams/issues) labelled `v0.5`,
`v1`, and `v2` are the planning surface.

## Contributing

PRs welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for dev setup, the
locked architectural decisions ([`SPEC.md`](SPEC.md) §5 and §9), and the
new-adapter workflow.

Found a bug or a security issue? See [`SECURITY.md`](SECURITY.md).

## License

MIT. See [`LICENSE`](LICENSE).
