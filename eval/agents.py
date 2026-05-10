"""
eval.agents
-----------

`AgentRunner` implementations. v0 ships:

- `ClaudeCodeRunner` — primary, aligns with the flagship `claude_code` adapter.
- `AiderRunner`     — kept for parity with the aider adapter.

The runner protocol's return value is informational; task success is decided
by the per-task `score()` callable, so a runner only needs to actually invoke
the agent and (for the dreamed condition) drop AGENTS.md into the workspace.

## Transcript capture (v0.0.2 two-pass eval)

`ClaudeCodeRunner` accepts an optional `capture_to: Path` directory. When set,
the agent runs with `claude --output-format stream-json --no-session-persistence`
and the streaming NDJSON is redirected to `capture_to / transcript.jsonl`.
That file becomes the input the consolidator reflects on, so pass-2 (dreamed)
sees memory derived from this codebase's own pass-1 (baseline) runs.

We chose stream-json over diffing `~/.claude/projects/<slug>/` because it's
deterministic (no slug rule, no race), supports `--no-session-persistence`
(no leftover state on the host), and is documented (`--output-format` is
stable Claude Code surface). The output uses the same `type: user|assistant`
event shape as the project-dir jsonl, so the existing `claude_code` adapter
ingests it directly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from eval.runner import EvalTask


class TranscriptCaptureError(RuntimeError):
    """The capture file was missing/empty/unparseable after `claude --print` ran.

    Raised when `capture_to` is set but the transcript can't be used downstream.
    Two-pass eval halts on this rather than silently degrading the consolidator's
    input — a failed pass-1 capture produces nothing useful for pass-2.
    """


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

    When `capture_to` is set (two-pass eval pass-1), the agent runs with
    `--output-format stream-json --no-session-persistence` and the streaming
    NDJSON lands at `capture_to / transcript.jsonl`. After the run, the file
    is validated to contain at least one `user`/`assistant` event; a failure
    raises `TranscriptCaptureError` so the orchestrator can halt cleanly.
    """

    claude_binary: str = "claude"
    capture_to: Path | None = None
    # `--print` runs non-interactively; `--dangerously-skip-permissions` is
    # required so the agent can actually edit files in the workspace without
    # an interactive permission prompt (which would block forever in a
    # `--print` subprocess and cause a timeout without producing changes).
    extra_args: tuple[str, ...] = (
        "--print",
        "--dangerously-skip-permissions",
    )

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

        capture_args: tuple[str, ...] = ()
        capture_file: Path | None = None
        if self.capture_to is not None:
            self.capture_to.mkdir(parents=True, exist_ok=True)
            capture_file = self.capture_to / "transcript.jsonl"
            # `--no-session-persistence` keeps `~/.claude/projects/` clean of
            # eval traffic; we own the transcript via stream-json redirection.
            capture_args = (
                "--output-format",
                "stream-json",
                "--verbose",  # required when --output-format=stream-json with --print
                "--no-session-persistence",
            )

        # Pass the prompt via stdin rather than as a positional argument:
        # `--add-dir <directories...>` is variadic and would otherwise greedily
        # consume the prompt as an additional directory path, leaving the agent
        # waiting for input that never arrives.
        cmd = [
            self.claude_binary,
            *self.extra_args,
            *capture_args,
            "--add-dir",
            str(workspace),
        ]

        if capture_file is not None:
            with capture_file.open("wb") as out:
                completed = subprocess.run(
                    cmd,
                    cwd=workspace,
                    input=task.prompt.encode("utf-8"),
                    stdout=out,
                    stderr=subprocess.PIPE,
                    timeout=task.timeout_seconds,
                )
            _validate_transcript(capture_file)
        else:
            completed = subprocess.run(
                cmd,
                cwd=workspace,
                input=task.prompt.encode("utf-8"),
                capture_output=True,
                timeout=task.timeout_seconds,
            )
        return completed.returncode == 0


def _validate_transcript(path: Path) -> None:
    """Assert `path` is a non-empty NDJSON stream with ≥1 user|assistant event.

    Raises `TranscriptCaptureError` otherwise — the consolidator can't reflect
    on an empty or malformed transcript.
    """
    if not path.exists() or path.stat().st_size == 0:
        raise TranscriptCaptureError(
            f"capture file {path} is missing or empty — claude --print produced "
            "no output. Check that `claude` is authenticated and the prompt is "
            "non-trivial."
        )
    seen_substantive = False
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate spurious non-JSON lines
            if event.get("type") in {"user", "assistant"}:
                seen_substantive = True
                break
    if not seen_substantive:
        raise TranscriptCaptureError(
            f"capture file {path} contains no user/assistant events. "
            "Claude Code's stream-json format may have changed; check the schema."
        )


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
