# tests/fixtures/

Anonymized real Claude Code session JSONLs used as input for the
`ClaudeCodeAdapter` test suite. They are committed to the repo, so anything
they leak is leaked **forever**; treat changes here with the same care as
secrets management.

## Files

| File | Source project | Notes |
|------|----------------|-------|
| `cc_session_61f500e5.jsonl` | OpenDreams (Desktop)         | short stub, ~1 message |
| `cc_session_c7ed2e78.jsonl` | Opendreams (Documents)       | interrupted bootstrap, 9 msgs |
| `cc_session_df98173b.jsonl` | AI-OpenDreams (Desktop)      | longer interrupted session, 19 msgs |

## Anonymizer (`anonymize.py`)

Regex-based scrubber. Run:

```
python -m tests.fixtures.anonymize <input.jsonl> <output.jsonl> [--scrub a,b,c]
```

### Categories the anonymizer handles

| Category | Examples scrubbed |
|---|---|
| **Paths** | `/Users/<name>/...`, `/home/<name>/...`, `/Users/<name>/(Desktop\|Documents\|Downloads\|src\|repos)/<project>` collapse to `/home/user/project` |
| **Bare host usernames** | Auto-detected from any `/Users/<name>` or `/home/<name>` path; scrubbed wherever they appear word-bounded (catches `ls -la`, `whoami`, `env`, `ps` output) |
| **Emails** | Any RFC-shaped address → `user@example.com` |
| **Git identity** | `Author: <name>` and `Committer: <name>` (from `git log`) → `Author: user` |
| **GitHub URLs** | `github.com/<owner>/<repo>` and `git@github.com:<owner>/<repo>` → `github.com/user/repo` |
| **OpenAI / Anthropic keys** | `sk-...`, `sk-ant-...`, `sk-proj-...` (≥20 chars) → `[redacted-key]` |
| **GitHub tokens** | `ghp_`, `gho_`, `ghs_`, `ghr_`, `ghu_`, `github_pat_` → `[redacted-key]` |
| **AWS access keys** | `AKIA...`, `ASIA...` → `[redacted-key]` |
| **Google API keys** | `AIza...` → `[redacted-key]` |
| **Slack tokens** | `xoxb-`, `xoxp-`, `xoxa-`, `xoxr-`, `xoxs-` → `[redacted-key]` |
| **JWTs** | `eyJ...eyJ...<sig>` triplets → `[redacted-jwt]` |
| **bcrypt hashes** | `$2a$`, `$2b$`, `$2y$` → `[redacted-hash]` |
| **PEM private-key blocks** | `-----BEGIN ... PRIVATE KEY-----...-----END ... PRIVATE KEY-----` → `[redacted-private-key]` |
| **Generic 32+ char hex** | commit hashes, request ids, etc. → `[redacted-token]` |
| **Caller-supplied terms** | `--scrub vincx2000,@octocat` for handles the auto-detector can't see |

### Categories deliberately NOT scrubbed

- IP addresses (no real risk in dev sessions; high false-positive cost)
- Hostnames / `.local` mDNS names
- Phone numbers, SSNs, credit-card numbers
- npm scoped package refs (`@anthropic-ai/sdk`, `@types/...`) — these are
  legitimate library identifiers, not PII
- Claude Code skill listings (`anthropic-skills:foo`, `init`, `review`) —
  product-level references, not user-identifying

If you need any of these scrubbed for a particular session, pass them via
`--scrub`.

### Known limitations

- Multi-line key blocks that aren't JSON-encoded with `\n` escapes (very
  rare in Claude Code JSONL since each event is one line).
- Identity strings that appear ONLY as bare words with no recognizable
  prefix/anchor (no `Author:` line, no `github.com/` URL, not in any
  `/Users/...` path). Use `--scrub` to add them explicitly.
- Anything inside binary or base64-encoded payloads.

## Audit log

| Date       | Auditor      | Findings | Action |
|------------|--------------|----------|--------|
| 2026-05-08 | session bot  | `vincx2000` (host GitHub handle) leaked through 4 `git log` Author lines in `df98173b`. `@anthropic-ai/sdk` and `anthropic-skills:` refs flagged then dismissed (legitimate package/skill names, not PII). | Extended anonymizer with `Author:`/`Committer:`/GitHub-URL/PAT/AWS/GCP/Slack/JWT/bcrypt/PEM patterns + `--scrub` CLI flag. Regenerated all 3 fixtures. Strengthened leak-detection test in `tests/test_claude_code_adapter.py::test_real_fixtures_have_no_pii_leaks` to cover every category the anonymizer claims. |

## Adding a new fixture

1. Run the anonymizer against the source `.jsonl`. Pass `--scrub <terms>` for
   any non-path identities (GitHub handles, Slack handles, etc.).
2. `grep` the output for anything that looks identifying.
3. Run the adapter against the fixture and grep the JSON dump.
4. Run `pytest tests/test_claude_code_adapter.py::test_real_fixtures_have_no_pii_leaks`
   — this is the gate.
5. If the leak test fires on a new category, **extend the anonymizer** and
   the leak-test list together so the regression can't recur.
