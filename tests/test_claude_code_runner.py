"""ClaudeCodeRunner tested against a fake `claude` binary on PATH."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from eval.agents import ClaudeCodeRunner, TranscriptCaptureError
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


# ---------- v0.0.2 two-pass eval: transcript capture ----------

def _make_fake_claude_streaming(tmp_path: Path, transcript_lines: list[str]) -> Path:
    """Drop a fake `claude` binary that prints `transcript_lines` to stdout.

    Mirrors `claude --output-format stream-json` behavior: each line is a
    self-contained JSON event. The fake also records argv so tests can assert
    the right flags were passed.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    argv_log = tmp_path / "claude_invocations.txt"
    transcript_payload = "\n".join(transcript_lines) + "\n"
    # Use printf to emit the exact bytes; redirect stdin to /dev/null so the
    # real prompt-on-stdin doesn't pollute the test.
    fake.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{argv_log}"\n'
        f"cat > /dev/null\n"  # consume stdin
        f"printf '%s' '{transcript_payload}'\n"
        "exit 0\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def test_runner_captures_streaming_transcript_to_file(tmp_path, monkeypatch):
    """When `capture_to` is set, the runner invokes claude with stream-json
    and redirects stdout to `capture_to/transcript.jsonl`."""
    transcript = [
        '{"type":"system","subtype":"init","cwd":"/x","session_id":"abc"}',
        '{"type":"user","message":{"role":"user","content":"please fix the bug"}}',
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"done"}]}}',
        '{"type":"result","subtype":"success"}',
    ]
    bin_dir = _make_fake_claude_streaming(tmp_path, transcript)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    task, workspace = _make_task(tmp_path)

    capture_dir = tmp_path / "capture"
    runner = ClaudeCodeRunner(capture_to=capture_dir)
    runner.run(task, workspace, opendream_md=None)

    # Capture file exists and contains the streamed events verbatim
    capture_file = capture_dir / "transcript.jsonl"
    assert capture_file.exists()
    body = capture_file.read_text()
    assert '"type":"user"' in body
    assert '"type":"assistant"' in body

    # Stream-json flags must be in argv when capture is enabled
    argv = (tmp_path / "claude_invocations.txt").read_text()
    assert "--output-format stream-json" in argv
    assert "--no-session-persistence" in argv


def test_runner_does_not_request_streaming_when_capture_off(tmp_path, monkeypatch):
    """Default (capture_to=None) preserves the v0.0.1 invocation: text
    output, no session-persistence flag — backward-compat for existing eval users."""
    bin_dir = _make_fake_claude_streaming(tmp_path, ['{"type":"result"}'])
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    task, workspace = _make_task(tmp_path)

    ClaudeCodeRunner().run(task, workspace, opendream_md=None)

    argv = (tmp_path / "claude_invocations.txt").read_text()
    assert "--output-format" not in argv
    assert "--no-session-persistence" not in argv


def test_runner_raises_when_capture_transcript_empty(tmp_path, monkeypatch):
    """If claude exits without writing any user/assistant events to stream-json
    output, the runner halts with TranscriptCaptureError. Two-pass eval relies
    on this to fail fast rather than feeding an empty transcript to the
    consolidator."""
    bin_dir = _make_fake_claude_streaming(
        tmp_path,
        # Only system + result events — no user/assistant
        ['{"type":"system"}', '{"type":"result"}'],
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    task, workspace = _make_task(tmp_path)

    runner = ClaudeCodeRunner(capture_to=tmp_path / "capture")
    with pytest.raises(TranscriptCaptureError, match="no user/assistant events"):
        runner.run(task, workspace, None)


def test_runner_raises_when_capture_file_missing_or_zero_bytes(tmp_path, monkeypatch):
    """If the capture file is empty (claude crashed before stdout flush),
    halt cleanly. Mirrors the empty-transcript case but exercises the size-0
    short-circuit in `_validate_transcript`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text("#!/bin/sh\ncat > /dev/null\nexit 0\n")  # writes nothing
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    task, workspace = _make_task(tmp_path)

    runner = ClaudeCodeRunner(capture_to=tmp_path / "capture")
    with pytest.raises(TranscriptCaptureError, match="missing or empty"):
        runner.run(task, workspace, None)
