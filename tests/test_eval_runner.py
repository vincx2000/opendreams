"""Tests for the eval harness against a fake AgentRunner and synthetic tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from eval.runner import EvalReport, EvalTask, TrialResult, load_tasks, run_eval


@dataclass
class FakeRunner:
    """Records calls; per-task success comes from the task's score.py."""

    behavior: callable  # type: ignore[type-arg]
    calls: list[tuple[str, bool]] = field(default_factory=list)

    def run(self, task: EvalTask, workspace: Path, opendream_md):
        dreamed = opendream_md is not None
        self.calls.append((task.task_id, dreamed))
        # The agent leaves a marker the score function can inspect.
        marker = workspace / ("dreamed.flag" if dreamed else "baseline.flag")
        marker.write_text(self.behavior(task.task_id, dreamed))
        return True


def _make_fixture(tmp_path: Path) -> Path:
    """A minimal codebase the runner copies into each trial workspace."""
    fx = tmp_path / "fixture"
    fx.mkdir()
    (fx / "x.txt").write_text("hello")
    return fx


def _make_task(
    tmp_path: Path,
    task_id: str,
    *,
    score_returns: str = "True",
    expected_test: bool = True,
) -> EvalTask:
    """Build a task directory inline. `score_returns` is a Python expression
    evaluated inside the task's score.py."""
    task_dir = tmp_path / f"task-{task_id}"
    task_dir.mkdir()
    (task_dir / "README.md").write_text(f"do the {task_id} task")
    if expected_test:
        (task_dir / "expected_test.py").write_text(
            "def test_dummy():\n    assert True\n"
        )
    (task_dir / "score.py").write_text(
        f"def score(workspace):\n    return {score_returns}\n"
    )
    return EvalTask(task_id=task_id, task_dir=task_dir)


# ----------------------------------------------------------- harness behavior


def test_run_eval_calls_runner_for_every_task_condition_trial(tmp_path):
    fixture = _make_fixture(tmp_path)
    tasks = [_make_task(tmp_path, "a"), _make_task(tmp_path, "b")]
    fake = FakeRunner(behavior=lambda *_: "ok")

    report = run_eval(
        tasks,
        fake,
        fixture_dir=fixture,
        trials=3,
        opendream_md=tmp_path / "AGENTS.md",
        workdir=tmp_path / "work",
    )

    # 2 tasks × 2 conditions × 3 trials = 12 rows
    assert len(report.trials) == 12
    assert sum(1 for c in fake.calls if c[1]) == 6  # dreamed
    assert sum(1 for c in fake.calls if not c[1]) == 6  # baseline


def test_run_eval_reports_lift_when_dreamed_outperforms(tmp_path):
    fixture = _make_fixture(tmp_path)
    # Score branches on the marker file the FakeRunner left.
    task = _make_task(
        tmp_path,
        "t1",
        score_returns="(workspace / 'dreamed.flag').exists()",
    )
    fake = FakeRunner(behavior=lambda *_: "ok")

    report = run_eval(
        [task],
        fake,
        fixture_dir=fixture,
        trials=5,
        opendream_md=tmp_path / "AGENTS.md",
        workdir=tmp_path / "work",
    )

    assert report.success_rate("baseline") == 0.0
    assert report.success_rate("dreamed") == 1.0
    assert report.lift_pp() == 100.0


def test_run_eval_counts_agent_exceptions_as_failures(tmp_path):
    fixture = _make_fixture(tmp_path)
    task = _make_task(tmp_path, "t", score_returns="True")

    def explode(*_):
        raise RuntimeError("boom")

    fake = FakeRunner(behavior=explode)
    report = run_eval(
        [task],
        fake,
        fixture_dir=fixture,
        trials=2,
        workdir=tmp_path / "work",
    )

    assert report.success_rate("baseline") == 0.0
    assert all(t.notes.startswith("agent exception") for t in report.trials)


def test_run_eval_drops_expected_test_into_workspace(tmp_path):
    fixture = _make_fixture(tmp_path)
    task = _make_task(
        tmp_path,
        "drop",
        # Score asserts the test file landed in the workspace's tests/ dir.
        score_returns="(workspace / 'tests' / 'test_drop.py').exists()",
    )
    fake = FakeRunner(behavior=lambda *_: "ok")
    report = run_eval(
        [task],
        fake,
        fixture_dir=fixture,
        trials=1,
        workdir=tmp_path / "work",
    )
    assert report.success_rate("baseline") == 1.0


# ----------------------------------------------------------- EvalReport


def test_eval_report_per_task_breakdown():
    report = EvalReport(
        trials=[
            TrialResult("a", "baseline", 0, success=True, duration_s=0.1),
            TrialResult("a", "baseline", 1, success=False, duration_s=0.1),
            TrialResult("a", "dreamed", 0, success=True, duration_s=0.1),
            TrialResult("a", "dreamed", 1, success=True, duration_s=0.1),
            TrialResult("b", "baseline", 0, success=False, duration_s=0.1),
            TrialResult("b", "dreamed", 0, success=True, duration_s=0.1),
        ]
    )
    breakdown = report.per_task()
    assert breakdown["a"]["baseline"] == 0.5
    assert breakdown["a"]["dreamed"] == 1.0
    assert breakdown["b"]["baseline"] == 0.0
    assert breakdown["b"]["dreamed"] == 1.0


# ----------------------------------------------------------- load_tasks


def test_load_tasks_picks_up_directories_with_readme_and_score(tmp_path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    valid = tasks_dir / "01_demo"
    valid.mkdir()
    (valid / "README.md").write_text("do something")
    (valid / "score.py").write_text("def score(w): return True\n")
    # Directory missing score.py — should be skipped
    incomplete = tasks_dir / "99_incomplete"
    incomplete.mkdir()
    (incomplete / "README.md").write_text("oops")
    # Loose file should be ignored
    (tasks_dir / "loose.txt").write_text("noise")

    found = load_tasks(tasks_dir)
    assert [t.task_id for t in found] == ["01_demo"]


def test_load_tasks_against_shipped_suite():
    """The shipped suite has 15 tasks; the runner must discover all of them."""
    tasks = load_tasks(Path(__file__).parent.parent / "eval" / "tasks")
    assert len(tasks) == 15
    # IDs should be lexicographically sorted (01_..., 02_..., ...)
    assert tasks[0].task_id.startswith("01_")
    assert tasks[-1].task_id.startswith("15_")


def test_eval_task_score_runs_score_py(tmp_path):
    task = _make_task(tmp_path, "imported", score_returns="True")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    assert task.score(workspace) is True

    failing = _make_task(tmp_path, "failing", score_returns="False")
    assert failing.score(workspace) is False
