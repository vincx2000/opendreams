---
name: Bug report
about: Something promised in the README or tests that doesn't hold
title: "[bug] "
labels: bug
assignees: ''
---

## What happened

<!-- One paragraph: what you did, what broke. -->

## Repro

```bash
# Minimal command sequence that reproduces the bug.
# If the bug is in a specific adapter, include the smallest fixture you can.
```

## Expected

<!-- What the README / docs / tests led you to expect. -->

## Actual

<!-- Paste the error, traceback, or surprising output here. -->

```
<paste error / output>
```

## Environment

- OpenDream version: <!-- `pip show opendream | grep Version`, or the commit SHA -->
- Python: <!-- `python --version` -->
- OS: <!-- macOS / Linux / Windows + version -->
- Adapter in use: <!-- claude_code / aider / generic_jsonl / custom -->
- LLM provider: <!-- openai / anthropic / Ollama via base_url / etc. -->

## Anything else

<!-- Logs, related issues, what you tried. -->
