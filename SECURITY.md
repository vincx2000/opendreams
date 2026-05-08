# Security policy

## Supported versions

OpenDream is at v0 — only the `main` branch is supported. There are no
backports.

## Reporting a vulnerability

**Please don't open public issues for security problems.** Use GitHub's
private vulnerability reporting:

1. Go to <https://github.com/vincx2000/opendreams/security/advisories/new>.
2. Describe what you found, what an attacker could do with it, and a
   reproduction recipe if you have one.

You'll get an acknowledgement within ~48h. v0 is a small project; expect a
single maintainer. There is no bug bounty.

## What's in scope

- Code execution paths in `opendream/` (CLI, adapters, LLM client, store,
  memory exporter).
- Test fixtures under `tests/fixtures/` — if any of the anonymized
  `.jsonl` files leak identifying data the
  [anonymizer](tests/fixtures/anonymize.py) didn't reach. The scrubber
  covers paths, emails, GitHub PATs, AWS / GCP / Slack keys, JWTs, bcrypt
  hashes, PEM private-key blocks, and bare host usernames detected from
  `/Users/<name>` and `/home/<name>` paths. See
  [`tests/fixtures/README.md`](tests/fixtures/README.md) for the full
  category list and audit log.
- The eval harness (`eval/runner.py`) — it shells out to agent runners and
  copies fixtures into per-trial workspaces. If the trial workspace can
  escape its sandbox, that's in scope.

## What's out of scope

- LLM provider key handling (we just pass `OPENAI_API_KEY` /
  `ANTHROPIC_API_KEY` through to the SDKs — provider-side issues belong
  to the provider).
- The hosted models themselves.
- Misuse of consolidated memory by the agent that reads `AGENTS.md`.
- Prompt-injection in user-supplied session content. Reflect and Consolidate
  prompts are not isolation boundaries against arbitrary text from the
  agent's own session — by design, the LLM gets to read everything the
  agent saw. If you treat OpenDream as a trust boundary, that's a
  configuration error.

## Local data

- `~/.opendream/db.sqlite` may contain the **raw text** of every agent
  session you've ingested. `chmod 600` it if your home directory is shared
  with other users. The CLI does not encrypt this file in v0.
- `<your project>/AGENTS.md` is whatever the consolidator produces — review
  it before committing it to a public repo. The exporter never adds raw
  session text, only consolidated patterns, but a poorly-tuned prompt can
  surface fragments. The
  [`opendream memory list`](README.md#prompt-tuning-loop) command shows the
  same content offline.
- Tests run **fully offline, with no network and no API key**. Adding a
  test that requires either is a CI failure.

## Coordinated disclosure

If you've reported something through the GitHub advisory flow, expect:

1. **48h** — acknowledgement.
2. **7 days** — assessment + draft fix.
3. **14 days** — fix released, advisory published with credit (your
   handle, unless you opt out).

If a fix takes longer, you'll get an explanation, not silence.
