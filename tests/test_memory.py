from __future__ import annotations

from uuid import uuid4

from opendream import memory, store
from opendream.trace import DreamCycle, MemoryEntry, MemoryUpdate


def _cycle(updates: list[MemoryUpdate]) -> DreamCycle:
    return DreamCycle(
        reflections_considered=[uuid4()],
        summary="test",
        updates=updates,
    )


def test_apply_cycle_add(tmp_db):
    cycle = _cycle(
        [
            MemoryUpdate(
                operation="add",
                kind="pattern",
                content="agent prefers small diffs",
                reason="seen 3x across reflections",
                evidence=[uuid4(), uuid4()],
                confidence="medium",
                scope="generalizable",
            )
        ]
    )
    memory.apply_cycle(cycle, path=tmp_db)

    entries = store.list_memory_entries(path=tmp_db)
    assert len(entries) == 1
    assert entries[0].kind == "pattern"
    assert entries[0].content == "agent prefers small diffs"
    assert len(entries[0].evidence_reflection_ids) == 2

    saved = store.list_dream_cycles(path=tmp_db)
    assert saved[0].applied is True
    assert saved[0].applied_at is not None


def test_apply_cycle_modify_overrides_content_and_reinforces(tmp_db):
    initial = MemoryEntry(
        kind="pattern", content="old text", scope="generalizable", confidence="low"
    )
    store.save_memory_entry(initial, path=tmp_db)

    cycle = _cycle(
        [
            MemoryUpdate(
                operation="modify",
                kind="pattern",
                target_id=initial.id,
                content="new precise text",
                reason="reinforced + refined",
                evidence=[uuid4()],
                confidence="high",
                scope="generalizable",
            )
        ]
    )
    memory.apply_cycle(cycle, path=tmp_db)

    [entry] = store.list_memory_entries(path=tmp_db)
    assert entry.id == initial.id
    assert entry.content == "new precise text"
    assert entry.confidence == "high"
    assert entry.last_reinforced_at >= initial.last_reinforced_at


def test_apply_cycle_deprecate(tmp_db):
    initial = MemoryEntry(
        kind="pattern", content="old rule", scope="generalizable", confidence="low"
    )
    store.save_memory_entry(initial, path=tmp_db)

    cycle = _cycle(
        [
            MemoryUpdate(
                operation="deprecate",
                kind="pattern",
                target_id=initial.id,
                reason="contradicted by reflection X",
                evidence=[uuid4()],
                confidence="high",
                scope="generalizable",
            )
        ]
    )
    memory.apply_cycle(cycle, path=tmp_db)

    assert store.list_memory_entries(path=tmp_db) == []
    [entry] = store.list_memory_entries(include_deprecated=True, path=tmp_db)
    assert entry.deprecated_at is not None
    assert entry.deprecation_reason == "contradicted by reflection X"


def test_apply_cycle_unknown_target_is_skipped(tmp_db):
    cycle = _cycle(
        [
            MemoryUpdate(
                operation="modify",
                kind="pattern",
                target_id=uuid4(),
                content="never lands",
                reason="orphan",
                evidence=[],
                confidence="low",
                scope="generalizable",
            )
        ]
    )
    memory.apply_cycle(cycle, path=tmp_db)
    assert store.list_memory_entries(include_deprecated=True, path=tmp_db) == []


def test_export_markdown_groups_by_kind(tmp_path, tmp_db):
    store.save_memory_entry(
        MemoryEntry(kind="pattern", content="P1", scope="g", confidence="high"),
        path=tmp_db,
    )
    store.save_memory_entry(
        MemoryEntry(kind="failure_mode", content="F1", scope="g", confidence="medium"),
        path=tmp_db,
    )
    out = tmp_path / "OPENDREAM.md"
    written = memory.export_markdown(out, path=tmp_db)

    text = written.read_text()
    assert "# OpenDream consolidated memory" in text
    assert "## Pattern" in text
    assert "## Failure Mode" in text
    assert "- P1" in text
    assert "- F1" in text


def test_export_markdown_when_empty(tmp_path, tmp_db):
    out = tmp_path / "OPENDREAM.md"
    memory.export_markdown(out, path=tmp_db)
    text = out.read_text()
    assert "no consolidated memory yet" in text


def test_export_markdown_excludes_deprecated(tmp_path, tmp_db):
    from datetime import datetime

    store.save_memory_entry(
        MemoryEntry(kind="pattern", content="visible", scope="g", confidence="high"),
        path=tmp_db,
    )
    store.save_memory_entry(
        MemoryEntry(
            kind="pattern",
            content="hidden",
            scope="g",
            confidence="low",
            deprecated_at=datetime.utcnow(),
            deprecation_reason="bad",
        ),
        path=tmp_db,
    )
    out = tmp_path / "OPENDREAM.md"
    memory.export_markdown(out, path=tmp_db)
    text = out.read_text()
    assert "visible" in text
    assert "hidden" not in text
