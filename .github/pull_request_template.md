<!--
Thanks for opening a PR! A couple of housekeeping notes before you submit:
  - Single-purpose changes only. Split mixed-scope work into separate PRs.
  - CI must pass: `pytest -q && ruff check . && mypy opendream`.
  - No edits to opendream/trace.py, opendream/prompts/reflect.md, or
    opendream/prompts/consolidate.md without flagging — the spec-drift
    tests will fail on byte-mismatch and the schema is locked per SPEC.md §5.
  - No new runtime dependencies (max 6 — see CONTRIBUTING.md).
  - No live LLM calls in tests; mocks only.
-->

## What changed

<!-- 1–3 bullets. The diff doesn't need a paraphrase, just the load-bearing intent. -->

## Why

<!-- The motivation. Link to a matching issue if behavior-changing. -->

Closes #

## Verification

- [ ] `pytest -q` — all green
- [ ] `ruff check .` — clean
- [ ] `mypy opendream` — clean
- [ ] If a new adapter: malformed-input test added (see CONTRIBUTING.md)
- [ ] If a new CLI surface: documented in README and SPEC.md §7

## Breaking changes

<!-- Default: none. If yes, describe what users have to do to upgrade. -->

None.

## Anything reviewers should know

<!-- Tradeoffs you considered, alternatives you ruled out, follow-ups you
plan to file separately. -->
