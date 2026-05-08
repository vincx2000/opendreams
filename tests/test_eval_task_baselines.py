"""
Validates that every shipped eval task is baseline-correct:

- Bug-fix tasks (01–05) and feature tasks (06–10) must `score(fixture) == False`
  on the unmodified fixture, proving the bug or feature gap actually exists.
- Refactor tasks (11–13) must `score(fixture) == True` on the unmodified
  fixture, proving the existing test suite is green-to-start (the refactor's
  job is to *keep* it green).
- Test-addition tasks (14–15) must `score(fixture) == False` on the
  unmodified fixture, proving the agent's target test file isn't already
  present and passing.

This is the API-key-free guard rail for the eval. If any of these flip
unexpectedly later, either the fixture drifted out of sync with the task
spec or the bug got accidentally fixed elsewhere.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from eval.runner import EvalTask, load_tasks


REPO_ROOT = Path(__file__).parent.parent
FIXTURE = REPO_ROOT / "eval" / "fixtures" / "library_api"
TASKS_DIR = REPO_ROOT / "eval" / "tasks"


BUG_FIX_IDS = {
    "01_email_case_sensitivity",
    "02_isbn_normalization",
    "03_loan_due_date_validation",
    "04_member_name_whitespace",
    "05_isbn_regex_too_loose",
}
FEATURE_IDS = {
    "06_search_books_by_title",
    "07_bulk_create_members",
    "08_cancel_loan",
    "09_member_loan_history",
    "10_popular_books",
}
REFACTOR_IDS = {
    "11_extract_loan_validation_helper",
    "12_generic_repository_base",
    "13_typed_storage_dataclass",
}
TEST_ADDITION_IDS = {
    "14_test_translate_function",
    "15_test_create_member_service",
}


def _all_task_ids() -> set[str]:
    return BUG_FIX_IDS | FEATURE_IDS | REFACTOR_IDS | TEST_ADDITION_IDS


def _unmodified_workspace(tmp_path: Path, task: EvalTask) -> Path:
    """Replicate what `run_eval` does: copy the fixture and drop the task's
    expected_test.py into workspace/tests/ — but make NO agent edits."""
    workspace = tmp_path / f"ws-{task.task_id}"
    shutil.copytree(FIXTURE, workspace)
    if task.expected_test_path.exists():
        (workspace / "tests").mkdir(parents=True, exist_ok=True)
        shutil.copy(
            task.expected_test_path,
            workspace / "tests" / f"test_{task.task_id}.py",
        )
    return workspace


@pytest.fixture(scope="module")
def loaded_tasks() -> dict[str, EvalTask]:
    tasks = load_tasks(TASKS_DIR)
    return {t.task_id: t for t in tasks}


def test_all_15_tasks_are_discovered(loaded_tasks):
    assert set(loaded_tasks) == _all_task_ids()


def test_task_id_categories_partition_the_suite():
    """The four category sets together must cover all 15 tasks with no
    overlap — keeps this file in sync with the suite."""
    union = BUG_FIX_IDS | FEATURE_IDS | REFACTOR_IDS | TEST_ADDITION_IDS
    assert len(union) == 15
    assert len(BUG_FIX_IDS) + len(FEATURE_IDS) + len(REFACTOR_IDS) + len(
        TEST_ADDITION_IDS
    ) == 15  # no overlap


@pytest.mark.parametrize("task_id", sorted(BUG_FIX_IDS))
def test_bug_fix_task_fails_on_unmodified_fixture(task_id, tmp_path, loaded_tasks):
    """Bug exists in the baseline; expected_test should fail before any fix."""
    task = loaded_tasks[task_id]
    workspace = _unmodified_workspace(tmp_path, task)
    assert task.score(workspace) is False, (
        f"task {task_id!r} should fail on the unmodified fixture (bug present), "
        "but score returned True — either the bug was accidentally fixed in "
        "the fixture or the expected_test isn't actually exercising the bug."
    )


@pytest.mark.parametrize("task_id", sorted(FEATURE_IDS))
def test_feature_task_fails_on_unmodified_fixture(task_id, tmp_path, loaded_tasks):
    """Feature is missing in the baseline; expected_test should fail."""
    task = loaded_tasks[task_id]
    workspace = _unmodified_workspace(tmp_path, task)
    assert task.score(workspace) is False, (
        f"task {task_id!r} should fail on the unmodified fixture (feature "
        "missing), but score returned True."
    )


@pytest.mark.parametrize("task_id", sorted(REFACTOR_IDS))
def test_refactor_task_passes_on_unmodified_fixture(task_id, tmp_path, loaded_tasks):
    """Refactor's job is to keep the suite green — so baseline must be green."""
    task = loaded_tasks[task_id]
    workspace = _unmodified_workspace(tmp_path, task)
    assert task.score(workspace) is True, (
        f"task {task_id!r}'s baseline test suite is not green; the refactor "
        "task can't validate against a red baseline."
    )


@pytest.mark.parametrize("task_id", sorted(TEST_ADDITION_IDS))
def test_test_addition_task_fails_on_unmodified_fixture(task_id, tmp_path, loaded_tasks):
    """Agent must create the target test file; baseline shouldn't already pass."""
    task = loaded_tasks[task_id]
    workspace = _unmodified_workspace(tmp_path, task)
    assert task.score(workspace) is False, (
        f"task {task_id!r} should fail on the unmodified fixture (target "
        "test file missing), but score returned True — the test file may "
        "already exist."
    )
