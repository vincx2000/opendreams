# Changelog

All notable changes to OpenDream are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet — see [Roadmap](README.md#roadmap) for what's planned.

## [0.0.1] — 2026-05-08

Initial public release.

### Added

- **Three-stage pipeline** — `trace → reflect → consolidate → memory`.
  Reflect and Consolidate are deliberately separate LLM calls; SPEC.md §9
  pins this.
- **Three adapters on a polymorphic `Adapter` base** —
  - `claude_code` (flagship) reads `~/.claude/projects/<project>/<uuid>.jsonl`.
  - `aider` reads `<repo>/.aider.chat.history.md` (multi-session files).
  - `generic_jsonl` is the universal escape hatch — emit one Pydantic
    `Session` per JSONL line and any stack can ingest in <50 LOC.
- **Dual-backend LLM client** — OpenAI-compatible (default; covers OpenAI,
  Ollama, vLLM, Together, Groq, Fireworks via `OPENDREAM_LLM_BASE_URL`) and
  Anthropic native (selected via `OPENDREAM_LLM_PROVIDER=anthropic`).
- **`AGENTS.md` export** — idempotent section between
  `<!-- OPENDREAM:BEGIN -->` / `<!-- OPENDREAM:END -->`. Three behaviors
  covered: file absent (creates with header), markers present (replaces
  body), markers absent (appends without destroying user content).
- **`memory_embeddings` vec0 table** — wired but unused in v0 (helpers
  shipped so v0.5's MCP semantic-retrieval server can land without a
  storage migration).
- **Prompt-tuning loop** — `--dry-run` renders the prompt to disk without
  spending tokens; `--import-json [--from FILE]` validates a hand-authored
  JSON and stores it through the same path the LLM call would.
  `dream --review` opens the cycle in `$EDITOR` and re-validates on save.
- **`--max-message-chars N`** — caps each rendered message body for sessions
  whose Write/Edit tool calls embed full file contents (drops a typical
  638-msg Claude Code session from ~165K to ~50K tokens).
- **Eval harness** — 15 fixed tasks against an embedded FastAPI fixture
  (`eval/fixtures/library_api/`). Tasks 1–5 introduce the codebase's
  conventions through bug fixes; tasks 6–15 reuse them. Cross-task signal
  is the lift target.
- **CI** — GitHub Actions matrix on Python 3.11 and 3.12; ruff + mypy +
  pytest, all required to pass.
- **171 tests** — every code path tested offline, no API key required.
  Includes a spec-drift guard that asserts `opendream/trace.py`,
  `opendream/prompts/reflect.md`, and `opendream/prompts/consolidate.md`
  match `SPEC.md` §11/§12/§13 byte-for-byte.
- **PII fixture audit** — 3 anonymized real Claude Code sessions under
  `tests/fixtures/cc_session_*.jsonl`, scrubbed via
  `tests/fixtures/anonymize.py` against a 14-category pattern list (paths,
  emails, GitHub PATs, AWS keys, GCP keys, Slack tokens, JWTs, bcrypt,
  PEM blocks, …). Audit log lives in `tests/fixtures/README.md`.

### Known limitations

- **Eval lift number not yet measured.** The README still shows
  `[EVAL_LIFT_PCT]` and `[EVAL_DATE]` placeholders — these get filled by an
  actual run on a host with a `claude` CLI on `PATH` and an LLM API key.
- **No PyPI package yet.** Install from source via `pip install -e .`
  inside a clone. Coming to PyPI in `0.0.2` once the eval number is in.
- **No dynamic memory retrieval.** v0 only writes static `AGENTS.md`. MCP
  server lands in v0.5.
- **Aider's tool-use blocks stay inlined as raw text** (Markdown fenced
  blocks) rather than getting parsed into `Message.tool_input`. Structured
  extraction is a v0.5 improvement.

### Security

No CVEs. PII fixtures audited per `tests/fixtures/README.md`. Vulnerability
reporting path documented in [`SECURITY.md`](SECURITY.md).

[Unreleased]: https://github.com/vincx2000/opendreams/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/vincx2000/opendreams/releases/tag/v0.0.1
