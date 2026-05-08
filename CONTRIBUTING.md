# Contributing to OpenDream

Thanks for thinking about contributing. OpenDream is a small, opinionated v0
codebase — the architecture is deliberately constrained so the project stays
shippable. Read this before opening a PR.

## Dev setup

```bash
git clone https://github.com/vincx2000/opendreams && cd opendreams
pip install -e ".[dev]"
```

That's it. No Docker, no compose, no service dependencies. SQLite is stdlib;
sqlite-vec ships its own native extension via pip.

## Running the test suite

```bash
pytest -q              # 171 tests, all green offline
ruff check .           # zero issues
mypy opendream         # zero issues across 13 source files
```

**No API key is required to run the tests.** Every test that touches the
LLM uses the mock pattern — see [`tests/test_reflect.py`](tests/test_reflect.py)
and [`tests/test_consolidate.py`](tests/test_consolidate.py) for examples
(stub class with a `complete_json(system, user)` method monkeypatched onto
the module's `LLMClient`). Follow that pattern in any new test that exercises
a code path crossing into `opendream/llm.py`.

## Locked architectural decisions

These are not up for debate in v0 — see [`SPEC.md`](SPEC.md) §5 and §9 for
the full reasoning. Bullet form:

- **Reflect and Consolidate are separate LLM calls.** Do not fuse them.
  Stage 1 runs per session; Stage 2 runs across many sessions. Different
  cognitive jobs.
- **Maximum six runtime dependencies.** Currently:
  `pydantic`, `openai`, `anthropic`, `sqlite-vec`, `typer`, `rich`. A
  feature that "needs a seventh dep" is probably out of scope for v0.
- **AGENTS.md is the only memory injection surface.** Static, idempotent,
  between `<!-- OPENDREAM:BEGIN -->` and `<!-- OPENDREAM:END -->`. No
  dynamic retrieval, no MCP server in v0 (those land in v0.5).
- **Evidence is mandatory.** Every observation cites a session reference;
  every memory update cites reflection ids. No evidence ⇒ the entry is
  rejected.
- **Memory must shrink as well as grow.** The consolidator is required to
  consider deprecation. Dream prompts that only accumulate produce noise.
- **No daemon, no scheduler, no web UI in v0.** All triggers are CLI
  commands.

If you think one of these needs to flex, open a discussion before a PR —
the bar to break a locked decision is "the alternative is demonstrably
worse on real data".

## Adding a new adapter

Most contributions probably look like this. The full template is in
[`docs/ADAPTERS.md`](docs/ADAPTERS.md), but the shape is:

1. Subclass `opendream.adapters.base.Adapter`.
2. Set a `name` and implement `discover_sessions(root)` and
   `parse_sessions(path) -> list[Session]`.
3. Decorate with `@register_adapter`.
4. Add at least one **malformed-input test** alongside the happy-path tests.
   Real history files are messy; adapters that crash on a single bad row are
   rejected.

The aider, claude_code, and generic_jsonl adapters are reference
implementations.

## Pull request checklist

Before opening a PR:

- [ ] CI is green locally (`pytest -q && ruff check . && mypy opendream`).
- [ ] Single-purpose change. If it touches more than one concern, split it.
- [ ] Behavior changes link to a matching issue.
- [ ] No live LLM calls in tests; mocks only.
- [ ] No new runtime dependencies (or a clear argument for going to seven).
- [ ] No edits to `opendream/trace.py`, `opendream/prompts/reflect.md`, or
      `opendream/prompts/consolidate.md` without flagging — the spec-drift
      tests will fail on byte-mismatch, and the schema is locked per §5.
- [ ] Anonymized any new fixture under `tests/fixtures/` (see
      [`tests/fixtures/README.md`](tests/fixtures/README.md)).

## Issue triage

Open issues land in one of three buckets:

- `bug` — something promised in the README or tests that doesn't hold.
- `v0.5` — features that fit the v0.5 architectural bumps (MCP retrieval,
  structured tool extraction).
- `v1` — multi-agent / federated work.

Anything else gets discussed before label.

## Be respectful

This is a small project. Disagreement is welcome; condescension and
hostility are not. The reviewer's job is to merge your work, not to teach
you Python — so come with a working PR and we'll meet in the middle.
