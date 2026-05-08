"""
opendream.memory
----------------

Apply DreamCycles to the consolidated memory store, and export the active
memory as `OPENDREAM.md` for the agent to read at session start.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from opendream import store
from opendream.trace import DreamCycle, MemoryEntry


KIND_ORDER = ("workflow", "pattern", "failure_mode", "preference", "fact")


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


def export_markdown(
    out_path: Path | str,
    path: Path | str | None = None,
) -> Path:
    """Write active memory entries to `out_path` as OPENDREAM.md."""
    entries = store.list_memory_entries(include_deprecated=False, path=path)
    sections: dict[str, list[MemoryEntry]] = {}
    for e in entries:
        sections.setdefault(e.kind, []).append(e)

    out = Path(out_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# OpenDream consolidated memory",
        "",
        f"_Generated {datetime.utcnow().isoformat(timespec='seconds')}Z_",
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
            lines.append(f"## {heading}")
            lines.append("")
            for e in kind_entries:
                lines.append(f"- {e.content}")
                lines.append(
                    f"  _(scope: {e.scope}, confidence: {e.confidence})_"
                )
            lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    return out.resolve()
