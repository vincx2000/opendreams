"""
Drift guards: keep SPEC.md's embedded files in sync with the actual files.

SPEC.md is the spec. §11 embeds `opendream/trace.py`, §12 embeds
`opendream/prompts/reflect.md`, §13 embeds `opendream/prompts/consolidate.md`.
The 3-week prompt-tuning loop is supposed to update both the file AND the
spec block atomically — these tests catch the case where someone touches one
and forgets the other.

The check is simple: extract the fenced code block from SPEC.md and
compare it byte-for-byte against the on-disk file (modulo the leading/
trailing fence markers).
"""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
SPEC_MD = REPO_ROOT / "SPEC.md"


def _extract_fenced_block(claude_md_text: str, header_anchor: str, fence: str) -> str:
    """Return the body of the fenced block that follows `header_anchor`.

    `fence` is the opening fence marker (`````python``, `````markdown``, etc.).
    Stops at the matching closing fence (same backtick count + length).
    """
    anchor_idx = claude_md_text.find(header_anchor)
    assert anchor_idx >= 0, f"anchor not found in SPEC.md: {header_anchor!r}"

    fence_open = claude_md_text.find(fence, anchor_idx)
    assert fence_open >= 0, f"opening fence not found after {header_anchor!r}"
    body_start = fence_open + len(fence)
    # The opening fence includes a trailing newline before the body.
    if claude_md_text[body_start] == "\n":
        body_start += 1

    # Closing fence is the same backtick run as the opening (without the
    # language tag), on its own line.
    backticks = re.match(r"`+", fence).group(0)
    close_pat = re.compile(rf"^{backticks}\s*$", re.MULTILINE)
    m = close_pat.search(claude_md_text, body_start)
    assert m, f"closing fence not found after {header_anchor!r}"
    return claude_md_text[body_start : m.start()]


def test_trace_py_matches_claude_md_section_11():
    """`opendream/trace.py` must equal the fenced block under §11."""
    spec = SPEC_MD.read_text(encoding="utf-8")
    embedded = _extract_fenced_block(
        spec,
        header_anchor="## 11. Embedded file: `opendream/trace.py`",
        fence="```python",
    )
    actual = (REPO_ROOT / "opendream" / "trace.py").read_text(encoding="utf-8")
    # Strip trailing whitespace on each side so a final-newline mismatch
    # doesn't fail the test for a non-substantive reason.
    assert embedded.rstrip() == actual.rstrip(), (
        "opendream/trace.py has drifted from SPEC.md §11. "
        "Update SPEC.md or the file — they must match exactly."
    )


def test_reflect_md_matches_claude_md_section_12():
    """`opendream/prompts/reflect.md` must equal the fenced block under §12."""
    spec = SPEC_MD.read_text(encoding="utf-8")
    embedded = _extract_fenced_block(
        spec,
        header_anchor="## 12. Embedded file: `opendream/prompts/reflect.md`",
        fence="````markdown",
    )
    actual = (REPO_ROOT / "opendream" / "prompts" / "reflect.md").read_text(
        encoding="utf-8"
    )
    assert embedded.rstrip() == actual.rstrip(), (
        "opendream/prompts/reflect.md has drifted from SPEC.md §12. "
        "The prompt-tuning loop must update both the file AND the spec block."
    )


def test_consolidate_md_matches_claude_md_section_13():
    """`opendream/prompts/consolidate.md` must equal the fenced block under §13."""
    spec = SPEC_MD.read_text(encoding="utf-8")
    embedded = _extract_fenced_block(
        spec,
        header_anchor="## 13. Embedded file: `opendream/prompts/consolidate.md`",
        fence="````markdown",
    )
    actual = (REPO_ROOT / "opendream" / "prompts" / "consolidate.md").read_text(
        encoding="utf-8"
    )
    assert embedded.rstrip() == actual.rstrip(), (
        "opendream/prompts/consolidate.md has drifted from SPEC.md §13."
    )
