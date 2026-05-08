"""
opendream.memory
----------------

Apply DreamCycles to the consolidated memory store, and export the active
memory into the project's `AGENTS.md` between idempotent OpenDream markers.

`AGENTS.md` is the cross-framework standard read by Cursor, Codex, OpenAI
agents, GitHub Copilot agent mode, and 60K+ repos. Claude Code users opt in
with `ln -s AGENTS.md CLAUDE.md`.

The exporter only ever rewrites the content between
`<!-- OPENDREAM:BEGIN -->` and `<!-- OPENDREAM:END -->`; everything else in
the file is left untouched.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from opendream import store
from opendream.trace import DreamCycle, MemoryEntry


KIND_ORDER = ("workflow", "pattern", "failure_mode", "preference", "fact")

BEGIN_MARKER = "<!-- OPENDREAM:BEGIN -->"
END_MARKER = "<!-- OPENDREAM:END -->"
_SECTION_RE = re.compile(
    rf"{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}",
    re.DOTALL,
)


def apply_cycle(cycle: DreamCycle, path: Path | str | None = None) -> DreamCycle:
    """Apply a DreamCycle's updates to the memory store, then mark it applied."""
    existing = {
        e.id: e
        for e in store.list_memory_entries(include_deprecated=True, path=path)
    }
    now = datetime.utcnow()

    for upd in cycle.updates:
        if upd.operation == "add":
            entry = MemoryEntry(
                kind=upd.kind,
                content=upd.content or "",
                scope=upd.scope,
                confidence=upd.confidence,
                created_at=now,
                last_reinforced_at=now,
                evidence_reflection_ids=list(upd.evidence),
            )
            store.save_memory_entry(entry, path=path)

        elif upd.operation == "modify":
            target = existing.get(upd.target_id) if upd.target_id else None
            if target is None:
                continue
            if upd.content:
                target.content = upd.content
            target.scope = upd.scope or target.scope
            target.confidence = upd.confidence
            target.last_reinforced_at = now
            target.evidence_reflection_ids = list(
                {*target.evidence_reflection_ids, *upd.evidence}
            )
            store.save_memory_entry(target, path=path)

        elif upd.operation == "deprecate":
            target = existing.get(upd.target_id) if upd.target_id else None
            if target is None:
                continue
            target.deprecated_at = now
            target.deprecation_reason = upd.reason
            store.save_memory_entry(target, path=path)

    cycle.applied = True
    cycle.applied_at = now
    store.save_dream_cycle(cycle, path=path)
    return cycle


def render_section_body(entries: list[MemoryEntry]) -> str:
    """Render the OpenDream-managed body of AGENTS.md (no markers, no outer fences)."""
    sections: dict[str, list[MemoryEntry]] = {}
    for e in entries:
        sections.setdefault(e.kind, []).append(e)

    lines = [
        "## OpenDream consolidated memory",
        "",
        f"_Generated {datetime.utcnow().isoformat(timespec='seconds')}Z. "
        "Managed by `opendream memory export`. "
        "Edit between the markers will be overwritten on next export._",
        "",
    ]
    if not entries:
        lines.append("_(no consolidated memory yet)_")
    else:
        for kind in KIND_ORDER:
            kind_entries = sections.get(kind, [])
            if not kind_entries:
                continue
            heading = kind.replace("_", " ").title()
            lines.append(f"### {heading}")
            lines.append("")
            for e in kind_entries:
                lines.append(f"- {e.content}")
                lines.append(
                    f"  _(scope: {e.scope}, confidence: {e.confidence})_"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_agents_md(
    out_path: Path | str = "AGENTS.md",
    path: Path | str | None = None,
) -> Path:
    """Write/refresh consolidated memory inside `out_path`'s OpenDream section.

    Behavior:
    - File doesn't exist: create it with a header + the marked block.
    - File exists with the markers: replace only the content between them.
    - File exists without the markers: append the marked block to the end.
      (Existing user content is never destroyed.)
    """
    entries = store.list_memory_entries(include_deprecated=False, path=path)
    body = render_section_body(entries)
    block = f"{BEGIN_MARKER}\n{body}{END_MARKER}\n"

    out = Path(out_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    if not out.exists():
        out.write_text(
            "# AGENTS.md\n\n"
            "Project guidance for AI agents. The block below is managed by OpenDream;\n"
            "everything else is yours to edit.\n\n"
            f"{block}",
            encoding="utf-8",
        )
        return out.resolve()

    existing = out.read_text(encoding="utf-8")
    if _SECTION_RE.search(existing):
        # Replace just the marked section, preserving everything else.
        new_content = _SECTION_RE.sub(block.rstrip(), existing, count=1)
        # Preserve trailing newline behavior of the original file.
        if existing.endswith("\n") and not new_content.endswith("\n"):
            new_content += "\n"
        out.write_text(new_content, encoding="utf-8")
    else:
        # No markers yet — append. Always separate with a blank line.
        sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
        out.write_text(existing + sep + block, encoding="utf-8")

    return out.resolve()


# Back-compat alias for callers (and tests) that still reference the old name.
export_markdown = export_agents_md
