"""
eval.scorers
------------

Shared score-function helpers. Per-task `score.py` files import from here
rather than reinventing the same `subprocess.run(["pytest", ...])` over and
over.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def pytest_passes(
    workspace: Path,
    test_target: str = "tests",
    *,
    timeout: int = 60,
) -> bool:
    """Run `pytest -q test_target` in workspace; return True iff exit code 0.

    `test_target` may be a test file path, a directory, or `-k EXPR` style
    selector — anything pytest would accept on the command line.
    """
    completed = subprocess.run(
        ["pytest", "-q", test_target],
        cwd=workspace,
        capture_output=True,
        timeout=timeout,
    )
    return completed.returncode == 0


def all_tests_pass(workspace: Path, *, timeout: int = 120) -> bool:
    """Run the entire test suite; return True iff every test passes."""
    return pytest_passes(workspace, "tests", timeout=timeout)


def pytest_passes_with_min_count(
    workspace: Path,
    test_file: str,
    min_passing: int,
    *,
    timeout: int = 60,
) -> bool:
    """Score helper for test-addition tasks.

    Runs `pytest -v test_file`; returns True iff exit code is 0 AND at least
    `min_passing` test cases passed in that file. Used when a task asks the
    agent to write N tests covering specific cases.
    """
    completed = subprocess.run(
        ["pytest", "-v", "--no-header", test_file],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        return False
    # `pytest -v` prints lines like "tests/foo.py::test_bar PASSED [ 33%]".
    passing = len(re.findall(r"PASSED\b", completed.stdout))
    return passing >= min_passing
