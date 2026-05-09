"""ClaudeCodeRunner tested against a fake `claude` binary on PATH."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from eval.agents import ClaudeCodeRunner
from eval.runner import EvalTask


def _make_fake_claude(tmp_path: Path, exit_code: int = 0) -> Path:
    """Drop a tiny shell script onto disk that records its argv AND stdin.

    argv lands in `claude_invocations.txt` (one line per call);
    stdin lands in `claude_stdin.txt` (raw bytes). Tests can assert on either.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    argv_log = tmp_path / "claude_invocations.txt"
    stdin_log = tmp_path / "claude_stdin.txt"
    fake.write_text(
        f"""#!/bin/sh
echo "$@" >> "{argv_log}"
cat >> "{stdin_log}"
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


def test_runner_invokes_claude_with_prompt_via_stdin_and_add_dir(tmp_path, monkeypatch):
    """Regression: `--add-dir <directories...>` is variadic in the real `claude`
    CLI, so passing the prompt as a trailing positional argument lets it be
    silently consumed as another directory. The runner now sends the prompt
    via stdin to keep argument parsing unambiguous."""
    bin_dir = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    task, workspace = _make_task(tmp_path)

    runner = ClaudeCodeRunner()
    runner.run(task, workspace, opendream_md=None)

    argv = (tmp_path / "claude_invocations.txt").read_text().strip()
    stdin = (tmp_path / "claude_stdin.txt").read_text()

    # argv should include --print, --dangerously-skip-permissions, and --add-dir <workspace>.
    # The prompt MUST NOT appear in argv (otherwise --add-dir's variadic parser eats it).
    assert "--print" in argv
    assert "--dangerously-skip-permissions" in argv
    assert f"--add-dir {workspace}" in argv
    assert "please fix the bug" not in argv, (
        "prompt leaked into argv — --add-dir is variadic and would consume it"
    )
    # Prompt arrives via stdin instead.
    assert "please fix the bug" in stdin


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
