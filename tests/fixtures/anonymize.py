"""
tests.fixtures.anonymize
------------------------

Strip user-identifying paths, usernames, credentials, and identity-shaped
metadata out of a Claude Code `.jsonl` session so it can be safely committed
as a test fixture.

Pipeline:
1. Auto-detect the host's Unix username(s) from any `/Users/<name>` or
   `/home/<name>` paths. Detected names are scrubbed wherever they appear
   bare (e.g. inside `ls -la`, `whoami`, `env`, `ps` output).
2. Apply pattern-based rewrites (paths, emails, key prefixes, identity
   metadata).
3. Optionally scrub additional caller-supplied terms via `extra_terms` /
   `--scrub`. Use this for handles that aren't in any path (GitHub usernames,
   Slack handles, etc.) and that the auto-detector therefore misses.

What is scrubbed (categories — see PATTERNS for the regex list):

  Paths           /Users/<name>/...   /home/<name>/...   →  /home/user
                  Common parents (Desktop/Documents/Downloads/src/repos)
                  collapse the trailing project segment to /home/user/project.

  Identity        Email addresses     →  user@example.com
                  `Author: <X>` and `Committer: <X>` (git log)  →  `Author: user`
                  github.com/<X>      →  github.com/user

  Credentials     sk-/sk-ant-/sk-proj- keys                  →  [redacted-key]
                  ghp_/github_pat_/gho_/ghs_ tokens           →  [redacted-key]
                  AKIA...AWS access keys, AIza...Google API keys → [redacted-key]
                  xoxb-/xoxp-/xoxa-/xoxr- Slack tokens         →  [redacted-key]
                  JWT-shaped strings (eyJ.eyJ.<sig>)           →  [redacted-jwt]
                  bcrypt hashes ($2[aby]$...)                  →  [redacted-hash]
                  SSH/PGP private-key blocks (single-line, JSON-encoded `\\n`)
                                                              →  [redacted-private-key]
                  Generic 32+ char hex tokens                  →  [redacted-token]

What is NOT scrubbed (known limitations):

  - Multi-line key blocks that aren't JSON-encoded (rare in Claude Code
    JSONL since each event is one line).
  - IP addresses (none observed in fixtures so far).
  - Hostnames / FQDNs / `.local` mDNS names.
  - Phone numbers, SSNs, credit-card numbers (extremely unlikely in dev
    sessions, not worth the false-positive risk).
  - GitHub usernames that appear ONLY as bare words (no `Author:` /
    `github.com/` prefix). Pass them via `--scrub` if you spot them.
  - `system` / `attachment` event payloads other than what the JSON-string
    content surfaces (the regex pass treats the entire JSONL as text).

Always spot-check the output. The leak-detection test in
tests/test_claude_code_adapter.py runs against every committed fixture and
will catch known-bad shapes that slip through.

Usage:
    python -m tests.fixtures.anonymize <input.jsonl> <output.jsonl>
    python -m tests.fixtures.anonymize <input.jsonl> <output.jsonl> --scrub vincx2000,@octocat
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


# Detect a Unix username from /Users/<name> or /home/<name>. Excludes 'user'
# (already-anonymized) so we don't loop on our own replacements.
_USERNAME_RE = re.compile(r"/(?:Users|home)/([A-Za-z0-9_\-]+)")

# Order matters: longer / more-specific path patterns first, then identity
# patterns, then key/credential patterns. We run identity patterns BEFORE
# generic key patterns so `Author: vincx2000 <user@example.com>` becomes
# `Author: user <user@example.com>` rather than leaving the name in place.
PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # ---- paths
    # /Users/<name>/Desktop/<Project>/something  →  /home/user/project/something
    (
        re.compile(
            r"/Users/[^/\s\"'\\]+/(?:Desktop|Documents|Downloads|src|repos)/[^/\s\"'\\]+"
        ),
        "/home/user/project",
    ),
    # /Users/<name>/...  → /home/user/...
    (re.compile(r"/Users/[^/\s\"'\\]+"), "/home/user"),
    # /home/<name>/...  → /home/user/... (skip if already 'user')
    (re.compile(r"/home/(?!user\b)[^/\s\"'\\]+"), "/home/user"),

    # ---- identity metadata (run BEFORE key patterns so names get scrubbed
    # even when they sit next to redacted commit hashes / emails)
    # Git log "Author: <name>" and "Committer: <name>" — captures up to a
    # space-then-`<` (the email bracket). Tolerates names with periods,
    # hyphens, apostrophes; stops at the `<` so we keep the email rewrite.
    (re.compile(r"(Author|Committer): [^<\\\"\n]+(?= <)"), r"\1: user"),
    # github.com/<owner>/<repo>  →  github.com/user/repo
    # Accepts owner+repo or just owner; preserves `.git` suffix if present.
    (
        re.compile(
            r"github\.com/(?!user/)[A-Za-z0-9_\-][A-Za-z0-9_\-.]*"
            r"(?:/[A-Za-z0-9_\-][A-Za-z0-9_\-.]*)?"
        ),
        "github.com/user/repo",
    ),
    # git@github.com:<owner>/<repo>.git  →  git@github.com:user/repo.git
    (
        re.compile(
            r"git@github\.com:(?!user/)[A-Za-z0-9_\-][A-Za-z0-9_\-.]*"
            r"/[A-Za-z0-9_\-][A-Za-z0-9_\-.]*"
        ),
        "git@github.com:user/repo",
    ),

    # ---- emails (after identity patterns so `Author: X <X@Y>` already lost the name)
    (re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), "user@example.com"),

    # ---- credentials
    # OpenAI / Anthropic / project-scoped keys
    (re.compile(r"sk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}"), "[redacted-key]"),
    # GitHub: classic PAT (`ghp_`), fine-grained (`github_pat_`), OAuth (`gho_`),
    # server-to-server (`ghs_`), refresh token (`ghr_`), user-to-server (`ghu_`)
    (re.compile(r"\b(?:ghp|gho|ghs|ghr|ghu)_[A-Za-z0-9]{30,}"), "[redacted-key]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}"), "[redacted-key]"),
    # AWS access key id (`AKIA...` or session-token `ASIA...`)
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[redacted-key]"),
    # Google Cloud / API key (`AIza...`)
    (re.compile(r"\bAIza[A-Za-z0-9_\-]{35}\b"), "[redacted-key]"),
    # Slack tokens
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]+"), "[redacted-key]"),
    # JWTs — three base64url segments separated by `.`. Restrict to ones
    # starting with `eyJ` (the encoded `{` of a real JWT header) to avoid
    # false positives on ordinary dotted strings.
    (
        re.compile(
            r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"
        ),
        "[redacted-jwt]",
    ),
    # bcrypt hashes
    (re.compile(r"\$2[aby]\$\d{1,2}\$[A-Za-z0-9./]{53}"), "[redacted-hash]"),
    # PEM-style private key blocks (single-line, JSON-escaped \n included).
    # Matches the smallest block from BEGIN to END so we don't over-grab.
    (
        re.compile(
            r"-----BEGIN [A-Z ]+PRIVATE KEY-----.*?-----END [A-Z ]+PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[redacted-private-key]",
    ),
    # Generic 32+ char hex tokens that look like keys / commit hashes /
    # request ids. Runs LAST so the more-specific patterns above win.
    (re.compile(r"\b[a-f0-9]{32,}\b"), "[redacted-token]"),
]


def detect_usernames(text: str) -> set[str]:
    """Return the set of Unix usernames found via `/Users/<name>` or `/home/<name>`."""
    return {m.group(1) for m in _USERNAME_RE.finditer(text) if m.group(1) != "user"}


def anonymize_text(s: str, extra_terms: tuple[str, ...] = ()) -> str:
    # Step 1+2: scrub bare username occurrences first, so they're caught even
    # in places where they appear without a leading slash (e.g. `ls -la` output).
    usernames = detect_usernames(s) | set(extra_terms)
    for name in sorted(usernames, key=len, reverse=True):
        s = re.sub(rf"\b{re.escape(name)}\b", "user", s)
    # Step 3: path / identity / key rewrites.
    for pat, repl in PATTERNS:
        s = pat.sub(repl, s)
    return s


def anonymize_file(
    src: Path, dst: Path, extra_terms: tuple[str, ...] = ()
) -> None:
    text = src.read_text(encoding="utf-8", errors="replace")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(anonymize_text(text, extra_terms=extra_terms), encoding="utf-8")


def _cli() -> None:
    parser = argparse.ArgumentParser(
        prog="anonymize",
        description="Scrub PII from a Claude Code .jsonl session for use as a test fixture.",
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--scrub",
        default="",
        help=(
            "Comma-separated extra terms to scrub bare-word (e.g. GitHub "
            "handles or other identifiers the auto-detector can't see)."
        ),
    )
    args = parser.parse_args()
    extras = tuple(t.strip() for t in args.scrub.split(",") if t.strip())
    anonymize_file(args.input, args.output, extra_terms=extras)
    print(f"wrote {args.output} ({args.output.stat().st_size} bytes)")
    if extras:
        print(f"  + scrubbed extra terms: {extras}")


if __name__ == "__main__":
    _cli()
