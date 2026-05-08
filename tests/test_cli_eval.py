"""Tests for the `opendream eval` CLI surface — list-tasks and run."""

from __future__ import annotations

import shutil
from pathlib import Path

from typer.testing import CliRunner

from opendream.cli import app


REPO_ROOT = Path(__file__).parent.parent


def test_eval_list_tasks_finds_all_15():
    r = CliRunner().invoke(
        app,
        ["eval", "list-tasks", "--tasks-dir", str(REPO_ROOT / "eval" / "tasks")],
    )
    assert r.exit_code == 0, r.stdout
    # Each task id should appear in the table
    for prefix in [
        "01_email",
        "05_isbn_regex",
        "06_search_books",
        "10_popular_books",
        "11_extract_loan",
        "13_typed_storage",
        "14_test_translate",
        "15_test_create_member",
    ]:
        assert prefix in r.stdout


def test_eval_list_tasks_handles_empty_dir(tmp_path):
    r = CliRunner().invoke(app, ["eval", "list-tasks", "--tasks-dir", str(tmp_path)])
    assert r.exit_code == 0
    assert "no tasks found" in r.stdout


def test_eval_run_rejects_baseline_and_dreamed_together(tmp_path):
    r = CliRunner().invoke(
        app,
        [
            "eval",
            "run",
            "--baseline",
            "--dreamed",
            "--tasks-dir",
            str(tmp_path),
            "--fixture",
            str(tmp_path),
        ],
    )
    assert r.exit_code != 0
    assert "mutually exclusive" in (r.stdout + (r.stderr or ""))


def test_eval_run_rejects_dreamed_without_agents_md(tmp_path):
    r = CliRunner().invoke(
        app,
        [
            "eval",
            "run",
            "--dreamed",
            "--tasks-dir",
            str(tmp_path),
            "--fixture",
            str(tmp_path),
        ],
    )
    assert r.exit_code != 0
    assert "--agents-md" in (r.stdout + (r.stderr or ""))


def test_eval_run_rejects_unknown_runner(tmp_path):
    r = CliRunner().invoke(
        app,
        [
            "eval",
            "run",
            "--runner",
            "openhands",  # not registered
            "--tasks-dir",
            str(tmp_path),
            "--fixture",
            str(tmp_path),
        ],
    )
    assert r.exit_code != 0
    assert "unknown --runner" in (r.stdout + (r.stderr or ""))


def test_eval_run_against_real_tasks_with_fake_runner(tmp_path, monkeypatch):
    """End-to-end: run the eval CLI on a 1-task subset with a no-op runner.
    Refactor task 11 should pass under both conditions because the suite is
    green to start with — gives us a clean exit-code-zero run-through of the
    full CLI path."""
    # Patch ClaudeCodeRunner with a no-op runner (just sets flag files)
    import eval.agents as agents_mod

    class NoopRunner:
        def run(self, task, workspace, opendream_md):
            (workspace / "agent_ran.flag").write_text("ok")
            return True

    monkeypatch.setattr(agents_mod, "ClaudeCodeRunner", NoopRunner)

    r = CliRunner().invoke(
        app,
        [
            "eval",
            "run",
            "--only",
            "11_extract",
            "--trials",
            "1",
            "--workdir",
            str(tmp_path / "work"),
            "--tasks-dir",
            str(REPO_ROOT / "eval" / "tasks"),
            "--fixture",
            str(REPO_ROOT / "eval" / "fixtures" / "library_api"),
        ],
    )
    assert r.exit_code == 0, r.stdout
    assert "11_extract_loan_validation_helper" in r.stdout
    # Task 11 is a refactor — baseline suite is green, so 100% under both conditions
    assert "100%" in r.stdout
    # Cleanup
    shutil.rmtree(tmp_path / "work", ignore_errors=True)
