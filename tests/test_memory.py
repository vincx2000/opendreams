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


def test_export_creates_agents_md_with_markers_when_absent(tmp_path, tmp_db):
    store.save_memory_entry(
        MemoryEntry(kind="pattern", content="P1", scope="g", confidence="high"),
        path=tmp_db,
    )
    store.save_memory_entry(
        MemoryEntry(kind="failure_mode", content="F1", scope="g", confidence="medium"),
        path=tmp_db,
    )
    out = tmp_path / "AGENTS.md"
    written = memory.export_agents_md(out, path=tmp_db)

    text = written.read_text()
    assert text.startswith("# AGENTS.md")
    assert memory.BEGIN_MARKER in text
    assert memory.END_MARKER in text
    assert "## OpenDream consolidated memory" in text
    assert "### Pattern" in text
    assert "### Failure Mode" in text
    assert "- P1" in text
    assert "- F1" in text


def test_export_when_memory_empty_writes_placeholder(tmp_path, tmp_db):
    out = tmp_path / "AGENTS.md"
    memory.export_agents_md(out, path=tmp_db)
    text = out.read_text()
    assert memory.BEGIN_MARKER in text and memory.END_MARKER in text
    assert "no consolidated memory yet" in text


def test_export_excludes_deprecated_entries(tmp_path, tmp_db):
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
    out = tmp_path / "AGENTS.md"
    memory.export_agents_md(out, path=tmp_db)
    text = out.read_text()
    assert "visible" in text
    assert "hidden" not in text


def test_export_replaces_only_marked_section_when_file_exists(tmp_path, tmp_db):
    store.save_memory_entry(
        MemoryEntry(kind="pattern", content="first export", scope="g", confidence="high"),
        path=tmp_db,
    )
    out = tmp_path / "AGENTS.md"
    initial = (
        "# AGENTS.md\n\n"
        "## My hand-written guidance\n\n"
        "Don't touch this section.\n\n"
        f"{memory.BEGIN_MARKER}\nstale opendream content\n{memory.END_MARKER}\n\n"
        "## More user content below\n\n"
        "Also keep me.\n"
    )
    out.write_text(initial, encoding="utf-8")

    memory.export_agents_md(out, path=tmp_db)
    text = out.read_text()

    # User content preserved on both sides of the marked section.
    assert "Don't touch this section." in text
    assert "Also keep me." in text
    # Stale content replaced.
    assert "stale opendream content" not in text
    assert "first export" in text
    # Markers still exactly once.
    assert text.count(memory.BEGIN_MARKER) == 1
    assert text.count(memory.END_MARKER) == 1


def test_export_appends_when_file_exists_without_markers(tmp_path, tmp_db):
    store.save_memory_entry(
        MemoryEntry(kind="pattern", content="appended", scope="g", confidence="high"),
        path=tmp_db,
    )
    out = tmp_path / "AGENTS.md"
    initial = "# Project guidance\n\nKeep all of this.\n"
    out.write_text(initial, encoding="utf-8")

    memory.export_agents_md(out, path=tmp_db)
    text = out.read_text()
    assert text.startswith(initial)
    assert memory.BEGIN_MARKER in text
    assert memory.END_MARKER in text
    assert "appended" in text


def test_export_is_idempotent_across_repeated_calls(tmp_path, tmp_db):
    store.save_memory_entry(
        MemoryEntry(kind="pattern", content="stable rule", scope="g", confidence="high"),
        path=tmp_db,
    )
    out = tmp_path / "AGENTS.md"
    memory.export_agents_md(out, path=tmp_db)
    after_first = out.read_text()
    memory.export_agents_md(out, path=tmp_db)
    after_second = out.read_text()
    # Only differs by the timestamp line; structure stable, no duplicate sections.
    assert after_first.count(memory.BEGIN_MARKER) == 1
    assert after_second.count(memory.BEGIN_MARKER) == 1
    assert after_first.count("stable rule") == after_second.count("stable rule") == 1


def test_export_markdown_alias_still_works(tmp_path, tmp_db):
    """Back-compat alias for the old name."""
    out = tmp_path / "AGENTS.md"
    written = memory.export_markdown(out, path=tmp_db)
    assert written.exists()
    assert memory.BEGIN_MARKER in written.read_text()


def test_memory_show_unknown_id_exits_nonzero(tmp_db):
    """`opendream memory show <missing-id>` should exit non-zero so scripts
    can detect the failure (parity with `sessions show` and `reflections show`)."""
    from uuid import uuid4

    from typer.testing import CliRunner

    from opendream.cli import app

    r = CliRunner().invoke(
        app, ["memory", "show", str(uuid4()), "--path", str(tmp_db)]
    )
    assert r.exit_code != 0
    assert "not found" in r.stdout
