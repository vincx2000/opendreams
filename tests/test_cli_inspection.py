"""Tests for `opendream sessions show`, `reflections list/show`, `dreams list`."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from typer.testing import CliRunner

from opendream import store
from opendream.cli import app
from opendream.trace import (
    Approach,
    DreamCycle,
    MemoryUpdate,
    Outcome,
    Reflection,
    SessionObservations,
    TaskClassification,
)


def _seed_full_state(db_path, sample_session) -> tuple[Reflection, DreamCycle]:
    store.save_session(sample_session, path=db_path)
    tc = TaskClassification(type="bug_fix", domain="py", complexity="trivial")
    ref = Reflection(
        session_id=sample_session.id,
        session_completeness="completed",
        reflection_confidence="medium",
        target_task_classification=tc,
        observed_work_classification=tc,
        approach=Approach(strategy_summary="x", tool_sequence=[]),
        observations=SessionObservations(),
        outcome=Outcome(completed=True, user_satisfied=True, evidence="green"),
    )
    store.save_reflection(ref, path=db_path)
    cycle = DreamCycle(
        reflections_considered=[ref.id],
        summary="seeded for test",
        updates=[
            MemoryUpdate(
                operation="add",
                kind="pattern",
                content="seeded entry",
                reason="test",
                evidence=[ref.id],
                confidence="medium",
                scope="generalizable",
            )
        ],
        applied=True,
        applied_at=datetime.utcnow(),
    )
    store.save_dream_cycle(cycle, path=db_path)
    return ref, cycle


# ----------------------------------------------------------- sessions show


def test_sessions_show_prints_messages(tmp_db, sample_session):
    store.save_session(sample_session, path=tmp_db)
    r = CliRunner().invoke(
        app,
        ["sessions", "show", str(sample_session.id), "--path", str(tmp_db)],
    )
    assert r.exit_code == 0, r.stdout
    assert str(sample_session.id) in r.stdout
    assert sample_session.task_description in r.stdout
    # First message content should appear
    assert "fix the null pointer" in r.stdout


def test_sessions_show_unknown_id_returns_nonzero(tmp_db):
    r = CliRunner().invoke(
        app, ["sessions", "show", str(uuid4()), "--path", str(tmp_db)]
    )
    assert r.exit_code != 0
    assert "not found" in r.stdout


def test_sessions_show_respects_limit(tmp_db, sample_session):
    store.save_session(sample_session, path=tmp_db)
    r = CliRunner().invoke(
        app,
        [
            "sessions",
            "show",
            str(sample_session.id),
            "--limit",
            "1",
            "--path",
            str(tmp_db),
        ],
    )
    assert r.exit_code == 0
    assert "more messages" in r.stdout


# ----------------------------------------------------------- reflections list/show


def test_reflections_list_empty(tmp_db):
    r = CliRunner().invoke(app, ["reflections", "list", "--path", str(tmp_db)])
    assert r.exit_code == 0
    assert "no reflections yet" in r.stdout


def test_reflections_list_shows_seeded(tmp_db, sample_session):
    ref, _cycle = _seed_full_state(tmp_db, sample_session)
    r = CliRunner().invoke(app, ["reflections", "list", "--path", str(tmp_db)])
    assert r.exit_code == 0, r.stdout
    # Rich wraps UUIDs across cell lines; check a unique prefix.
    assert str(ref.id)[:8] in r.stdout
    assert "completed" in r.stdout
    assert "medium" in r.stdout


def test_reflections_show_pretty_prints_json(tmp_db, sample_session):
    ref, _cycle = _seed_full_state(tmp_db, sample_session)
    r = CliRunner().invoke(
        app, ["reflections", "show", str(ref.id), "--path", str(tmp_db)]
    )
    assert r.exit_code == 0, r.stdout
    assert '"session_completeness"' in r.stdout
    assert '"target_task_classification"' in r.stdout


def test_reflections_show_unknown_id(tmp_db):
    r = CliRunner().invoke(
        app, ["reflections", "show", str(uuid4()), "--path", str(tmp_db)]
    )
    assert r.exit_code != 0
    assert "not found" in r.stdout


# ----------------------------------------------------------- dreams list


def test_dreams_list_empty(tmp_db):
    r = CliRunner().invoke(app, ["dreams", "list", "--path", str(tmp_db)])
    assert r.exit_code == 0
    assert "no dream cycles yet" in r.stdout


def test_dreams_list_shows_seeded(tmp_db, sample_session):
    _ref, cycle = _seed_full_state(tmp_db, sample_session)
    r = CliRunner().invoke(app, ["dreams", "list", "--path", str(tmp_db)])
    assert r.exit_code == 0, r.stdout
    # Rich wraps UUIDs across cell lines; check a unique prefix.
    assert str(cycle.id)[:8] in r.stdout
    # applied=True, 1 update, 0 non_updates, 1 reflection considered
    assert "✓" in r.stdout
