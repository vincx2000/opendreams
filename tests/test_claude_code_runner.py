"""ClaudeCodeRunner tested against a fake `claude` binary on PATH."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from eval.agents import ClaudeCodeRunner
from eval.runner import EvalTask


def _make_fake_claude(tmp_path: Path, exit_code: int = 0) -> Path:
    """Drop a tiny shell script onto disk that records its argv into a file."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    log = tmp_path / "claude_invocations.txt"
    fake.write_text(
        f"""#!/bin/sh
echo "$@" >> "{log}"
exit {exit_code}
"""
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _make_task(tmp_path: Path) -> tuple[EvalTask, Path]:
    task_dir = tmp_path / "task-t"
    task_dir.mkdir()
    (task_dir / "README.md").write_text("please fix the bug")
    (task_dir / "score.py").write_text("def score(workspace):\n    return True\n")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "x.txt").write_text("baseline")

    task = EvalTask(task_id="t", task_dir=task_dir)
    return task, workspace


def test_runner_invokes_claude_with_prompt_and_add_dir(tmp_path, monkeypatch):
    bin_dir = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    task, workspace = _make_task(tmp_path)

    runner = ClaudeCodeRunner()
    runner.run(task, workspace, opendream_md=None)

    log = (tmp_path / "claude_invocations.txt").read_text().strip()
    # argv should include --print, --add-dir <workspace>, and the prompt
    assert "--print" in log
    assert f"--add-dir {workspace}" in log
    assert "please fix the bug" in log


def test_runner_drops_agents_md_in_dreamed_condition(tmp_path, monkeypatch):
    bin_dir = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    task, workspace = _make_task(tmp_path)

    md = tmp_path / "AGENTS_consolidated.md"
    md.write_text("<!-- OPENDREAM:BEGIN -->\nmemory\n<!-- OPENDREAM:END -->\n")

    runner = ClaudeCodeRunner()
    runner.run(task, workspace, opendream_md=md)

    dropped = workspace / "AGENTS.md"
    assert dropped.exists()
    assert "OPENDREAM:BEGIN" in dropped.read_text()


def test_runner_returns_false_on_nonzero_exit(tmp_path, monkeypatch):
    bin_dir = _make_fake_claude(tmp_path, exit_code=2)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    task, workspace = _make_task(tmp_path)
    assert ClaudeCodeRunner().run(task, workspace, None) is False


def test_runner_raises_when_binary_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    task, workspace = _make_task(tmp_path)
    with pytest.raises(RuntimeError, match="not on PATH"):
        ClaudeCodeRunner().run(task, workspace, None)
