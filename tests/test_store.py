from __future__ import annotations

import sqlite3
from datetime import datetime
from uuid import uuid4

import sqlite_vec

from opendream import store
from opendream.trace import (
    Approach,
    DreamCycle,
    MemoryEntry,
    MemoryUpdate,
    Outcome,
    Reflection,
    SessionObservations,
    TaskClassification,
)


def test_init_db_creates_expected_tables(tmp_path):
    db = tmp_path / "db.sqlite"
    store.init_db(db)

    conn = sqlite3.connect(db)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    conn.close()

    expected = {
        "sessions",
        "messages",
        "reflections",
        "memory_entries",
        "dream_cycles",
        "memory_embeddings",
    }
    assert expected.issubset(names)


def test_init_db_is_idempotent(tmp_path):
    db = tmp_path / "db.sqlite"
    store.init_db(db)
    store.init_db(db)


def test_session_round_trip(tmp_db, sample_session):
    store.save_session(sample_session, path=tmp_db)
    loaded = store.load_session(sample_session.id, path=tmp_db)
    assert loaded is not None
    assert loaded.id == sample_session.id
    assert loaded.agent == "aider"
    assert loaded.task_description == sample_session.task_description
    assert len(loaded.messages) == 3
    assert loaded.messages[1].content.startswith("Looking at parseUser")
    assert loaded.metadata == {"source": "test"}
    assert loaded.outcome_known is True
    assert loaded.outcome_success is True


def test_load_session_missing_returns_none(tmp_db):
    assert store.load_session(uuid4(), path=tmp_db) is None


def test_list_sessions_orders_by_started_at(tmp_db, sample_session):
    s2 = sample_session.model_copy(
        update={"id": uuid4(), "started_at": datetime(2026, 5, 2)}
    )
    s1 = sample_session.model_copy(
        update={"id": uuid4(), "started_at": datetime(2026, 5, 1)}
    )
    store.save_session(s2, path=tmp_db)
    store.save_session(s1, path=tmp_db)
    listed = store.list_sessions(path=tmp_db)
    assert [s.id for s in listed] == [s1.id, s2.id]


def test_reflection_round_trip(tmp_db, sample_session):
    store.save_session(sample_session, path=tmp_db)
    ref = Reflection(
        session_id=sample_session.id,
        task_classification=TaskClassification(
            type="bug_fix", domain="python", complexity="simple"
        ),
        approach=Approach(strategy_summary="read then patch", tool_sequence=["read", "edit"]),
        observations=SessionObservations(),
        outcome=Outcome(completed=True, user_satisfied=True, evidence="user said thanks"),
    )
    store.save_reflection(ref, path=tmp_db)
    loaded = store.load_reflection(ref.id, path=tmp_db)
    assert loaded is not None
    assert loaded.id == ref.id
    assert loaded.session_id == sample_session.id
    assert loaded.task_classification.type == "bug_fix"
    assert ref in store.list_reflections(path=tmp_db)


def test_memory_entry_round_trip_and_filter(tmp_db):
    active = MemoryEntry(
        kind="pattern", content="active rule", scope="generalizable", confidence="high"
    )
    deprecated = MemoryEntry(
        kind="pattern",
        content="old rule",
        scope="generalizable",
        confidence="low",
        deprecated_at=datetime(2026, 5, 1),
        deprecation_reason="contradicted",
    )
    store.save_memory_entry(active, path=tmp_db)
    store.save_memory_entry(deprecated, path=tmp_db)

    active_only = store.list_memory_entries(path=tmp_db)
    assert {e.id for e in active_only} == {active.id}

    everything = store.list_memory_entries(include_deprecated=True, path=tmp_db)
    assert {e.id for e in everything} == {active.id, deprecated.id}


def test_dream_cycle_round_trip(tmp_db):
    cycle = DreamCycle(
        reflections_considered=[uuid4()],
        summary="nothing surprising",
        updates=[
            MemoryUpdate(
                operation="add",
                kind="pattern",
                content="agent prefers small diffs",
                reason="seen 3x",
                evidence=[uuid4()],
                confidence="medium",
                scope="generalizable",
            )
        ],
    )
    store.save_dream_cycle(cycle, path=tmp_db)
    cycles = store.list_dream_cycles(path=tmp_db)
    assert len(cycles) == 1
    assert cycles[0].id == cycle.id
    assert cycles[0].updates[0].kind == "pattern"
