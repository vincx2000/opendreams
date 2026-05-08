"""
eval.agents
-----------

`AgentRunner` implementations. v0 ships:

- `ClaudeCodeRunner` — primary, aligns with the flagship `claude_code` adapter.
- `AiderRunner`     — kept for parity with the aider adapter.

The runner protocol's return value is informational; task success is decided
by the per-task `score()` callable, so a runner only needs to actually invoke
the agent and (for the dreamed condition) drop AGENTS.md into the workspace.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from eval.runner import EvalTask


@dataclass
class ClaudeCodeRunner:
    """Drives the `claude` CLI over a workspace in non-interactive print mode.

    Requires `claude` on PATH; auth is `claude`'s own (run `claude login`
    once on the host). We deliberately do not propagate `OPENDREAM_*_MODEL`
    env vars — `claude` is a runtime, not a model selector.

    For the dreamed condition, the consolidated `AGENTS.md` is copied into
    the workspace so Claude Code reads it on session start (Claude Code
    follows `AGENTS.md` natively when symlinked to `CLAUDE.md`; for the eval
    we drop `AGENTS.md` in the workspace and let the standard discovery
    mechanism find it).
    """

    claude_binary: str = "claude"
    # `--print` runs non-interactively; `--add-dir` constrains scope.
    # Verify exact flag names against `claude --help` once the CLI is installed.
    extra_args: tuple[str, ...] = ("--print",)

    def run(
        self,
        task: EvalTask,
        workspace: Path,
        opendream_md: Path | None,
    ) -> bool:
        if shutil.which(self.claude_binary) is None:
            raise RuntimeError(f"{self.claude_binary} not on PATH")
        if opendream_md:
            shutil.copy(opendream_md, workspace / "AGENTS.md")

        cmd = [
            self.claude_binary,
            *self.extra_args,
            "--add-dir",
            str(workspace),
            task.prompt,
        ]
        completed = subprocess.run(
            cmd,
            cwd=workspace,
            capture_output=True,
            timeout=task.timeout_seconds,
        )
        return completed.returncode == 0


@dataclass
class AiderRunner:
    """Drives `aider` over a workspace via its `--message` flag.

    Requires `aider` on PATH and an LLM API key in the environment. Kept for
    parity with the aider adapter; `ClaudeCodeRunner` is the primary v0 runner.
    """

    aider_binary: str = "aider"
    extra_args: tuple[str, ...] = ("--yes", "--no-auto-commits")

    def run(
        self,
        task: EvalTask,
        workspace: Path,
        opendream_md: Path | None,
    ) -> bool:
        if shutil.which(self.aider_binary) is None:
            raise RuntimeError(f"{self.aider_binary} not on PATH")
        if opendream_md:
            shutil.copy(opendream_md, workspace / "AGENTS.md")
        completed = subprocess.run(
            [self.aider_binary, *self.extra_args, "--message", task.prompt],
            cwd=workspace,
            capture_output=True,
            timeout=task.timeout_seconds,
        )
        return completed.returncode == 0
