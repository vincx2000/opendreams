"""
Tests for memory accumulation/deprecation across multiple dream cycles.

Round-trips DreamCycles through `memory.apply_cycle` to verify:
- mixed add+modify+deprecate in a single cycle land independently
- AGENTS.md export reflects the current state after N cycles, not just the
  last one
- deprecation in cycle N+1 hides an entry that was added in cycle N
- modify in cycle N+1 reinforces (`last_reinforced_at` advances) AND
  appends new evidence reflection ids without overwriting prior ones
"""

from __future__ import annotations

import time
from uuid import uuid4

from opendream import memory, store
from opendream.trace import DreamCycle, MemoryUpdate


def _add(content: str, kind: str = "pattern", scope: str = "generalizable",
         confidence: str = "medium", evidence=None) -> MemoryUpdate:
    return MemoryUpdate(
        operation="add",
        kind=kind,
        target_id=None,
        content=content,
        reason="test add",
        evidence=evidence or [uuid4()],
        confidence=confidence,
        scope=scope,
    )


def _modify(target_id, content, evidence=None) -> MemoryUpdate:
    return MemoryUpdate(
        operation="modify",
        kind="pattern",
        target_id=target_id,
        content=content,
        reason="test modify",
        evidence=evidence or [uuid4()],
        confidence="high",
        scope="generalizable",
    )


def _deprecate(target_id, reason="superseded") -> MemoryUpdate:
    return MemoryUpdate(
        operation="deprecate",
        kind="pattern",
        target_id=target_id,
        reason=reason,
        evidence=[uuid4()],
        confidence="high",
        scope="generalizable",
    )


def _cycle(updates) -> DreamCycle:
    return DreamCycle(
        reflections_considered=[uuid4()],
        summary="multi-cycle test",
        updates=list(updates),
    )


def test_add_modify_deprecate_in_one_cycle_land_independently(tmp_db):
    """Mix all three operations in a single cycle; each should apply."""
    # Pre-seed two entries so modify/deprecate have targets.
    cycle_a = _cycle([
        _add("alpha entry"),
        _add("bravo entry"),
    ])
    memory.apply_cycle(cycle_a, path=tmp_db)
    [alpha, bravo] = store.list_memory_entries(path=tmp_db)

    cycle_b = _cycle([
        _add("charlie entry"),                       # new add
        _modify(alpha.id, "alpha entry (refined)"),  # in-place update
        _deprecate(bravo.id),                        # tombstone bravo
    ])
    memory.apply_cycle(cycle_b, path=tmp_db)

    active = sorted(
        store.list_memory_entries(path=tmp_db), key=lambda e: e.content
    )
    contents = [e.content for e in active]
    assert contents == ["alpha entry (refined)", "charlie entry"]

    # bravo is still there in the deprecated set
    all_entries = store.list_memory_entries(include_deprecated=True, path=tmp_db)
    deprecated = [e for e in all_entries if e.deprecated_at is not None]
    assert len(deprecated) == 1
    assert deprecated[0].content == "bravo entry"


def test_modify_reinforces_timestamp_and_appends_evidence(tmp_db):
    """`modify` updates `last_reinforced_at` and unions the evidence list."""
    initial_evidence = [uuid4(), uuid4()]
    cycle_1 = _cycle([_add("rule X", evidence=initial_evidence)])
    memory.apply_cycle(cycle_1, path=tmp_db)
    [entry] = store.list_memory_entries(path=tmp_db)
    initial_ts = entry.last_reinforced_at
    initial_evidence_set = set(entry.evidence_reflection_ids)

    # Sleep just enough that the new last_reinforced_at is strictly later.
    time.sleep(0.01)

    new_evidence = [uuid4()]
    cycle_2 = _cycle([_modify(entry.id, "rule X (refined)", evidence=new_evidence)])
    memory.apply_cycle(cycle_2, path=tmp_db)

    [refined] = store.list_memory_entries(path=tmp_db)
    assert refined.id == entry.id
    assert refined.content == "rule X (refined)"
    assert refined.last_reinforced_at > initial_ts
    # Evidence is the union — old + new, no overwrite
    assert initial_evidence_set <= set(refined.evidence_reflection_ids)
    assert new_evidence[0] in refined.evidence_reflection_ids


def test_deprecate_then_re_add_keeps_both_records(tmp_db):
    """Deprecating an entry then adding fresh content with the same kind
    creates a new entry; the deprecated one stays as a tombstone."""
    memory.apply_cycle(_cycle([_add("first version")]), path=tmp_db)
    [first] = store.list_memory_entries(path=tmp_db)

    memory.apply_cycle(_cycle([_deprecate(first.id)]), path=tmp_db)
    assert store.list_memory_entries(path=tmp_db) == []

    memory.apply_cycle(_cycle([_add("second version")]), path=tmp_db)
    active = store.list_memory_entries(path=tmp_db)
    assert len(active) == 1
    assert active[0].content == "second version"
    assert active[0].id != first.id

    # All entries (including deprecated) — the tombstone is preserved.
    all_entries = store.list_memory_entries(include_deprecated=True, path=tmp_db)
    assert len(all_entries) == 2
    assert {e.content for e in all_entries} == {"first version", "second version"}


def test_unknown_target_id_in_modify_or_deprecate_is_silently_skipped(tmp_db):
    """Bad target ids should not raise — they're silently dropped, since the
    consolidator may produce stale references and we don't want a single bad
    update to abort an entire cycle."""
    cycle = _cycle([
        _modify(uuid4(), "ghost"),       # target doesn't exist
        _deprecate(uuid4()),             # target doesn't exist
        _add("real entry"),              # this should still land
    ])
    memory.apply_cycle(cycle, path=tmp_db)

    entries = store.list_memory_entries(include_deprecated=True, path=tmp_db)
    assert len(entries) == 1
    assert entries[0].content == "real entry"


def test_agents_md_reflects_state_after_n_cycles(tmp_path, tmp_db):
    """AGENTS.md export shows current state, not the union of every cycle."""
    out = tmp_path / "AGENTS.md"

    # Cycle 1: add three entries
    memory.apply_cycle(
        _cycle([_add("workflow:A", kind="workflow"), _add("pattern:B"), _add("fact:C", kind="fact")]),
        path=tmp_db,
    )
    memory.export_agents_md(out, path=tmp_db)
    text = out.read_text()
    assert "workflow:A" in text and "pattern:B" in text and "fact:C" in text

    # Cycle 2: deprecate B, modify A, add D — look entries up by content
    # rather than positional sort (which gave a confusingly wrong assignment).
    by_content = {e.content: e for e in store.list_memory_entries(path=tmp_db)}
    a = by_content["workflow:A"]
    b = by_content["pattern:B"]
    memory.apply_cycle(
        _cycle([_modify(a.id, "workflow:A v2"), _deprecate(b.id), _add("preference:D", kind="preference")]),
        path=tmp_db,
    )
    memory.export_agents_md(out, path=tmp_db)
    text = out.read_text()
    assert "workflow:A v2" in text
    assert "pattern:B" not in text  # deprecated, hidden from active export
    assert "fact:C" in text
    assert "preference:D" in text


def test_agents_md_groups_by_kind_after_multiple_cycles(tmp_path, tmp_db):
    """Section headings stay one-per-kind regardless of cycle count."""
    memory.apply_cycle(
        _cycle([
            _add("p1"), _add("p2"),
            _add("w1", kind="workflow"),
        ]),
        path=tmp_db,
    )
    memory.apply_cycle(
        _cycle([
            _add("p3"),
            _add("f1", kind="fact"),
        ]),
        path=tmp_db,
    )
    out = tmp_path / "AGENTS.md"
    memory.export_agents_md(out, path=tmp_db)
    text = out.read_text()

    # Each kind heading appears once
    assert text.count("### Pattern") == 1
    assert text.count("### Workflow") == 1
    assert text.count("### Fact") == 1
    # Three patterns are all listed under the single Pattern heading
    pattern_idx = text.index("### Pattern")
    next_section = min(
        (i for i in (text.find("### Workflow"), text.find("### Fact"), len(text)) if i > pattern_idx),
    )
    pattern_block = text[pattern_idx:next_section]
    assert "p1" in pattern_block and "p2" in pattern_block and "p3" in pattern_block
