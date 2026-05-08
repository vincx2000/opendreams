"""
eval.runner
-----------

OpenDream eval harness: run a fixed task suite under two conditions
(baseline vs dreamed) and report the success-rate lift.

SPEC.md §3 ship criterion 3: this report is what the README quotes as the
"before/after" number. Target ≥ 5 percentage-point lift on a 15-task suite,
5 trials each.

## Task layout

Tasks live in `eval/tasks/<n>_<slug>/` and have three files each:

- `README.md`         — the prompt the agent sees.
- `expected_test.py`  — copied into the workspace's tests/ before the agent
                        runs, so pytest (when called by `score`) can pick it
                        up alongside the existing fixture tests.
- `score.py`          — exposes `def score(workspace: Path) -> bool`. Most
                        scorers delegate to helpers in `eval.scorers`.

All tasks operate on a shared fixture codebase (`eval/fixtures/library_api/`
by default). The runner copies the fixture into a fresh per-trial workspace,
drops the task's expected_test.py into `workspace/tests/`, runs the agent,
then calls `task.score(workspace)`.

## Running

```python
from pathlib import Path
from eval.runner import run_eval, load_tasks
from eval.agents import ClaudeCodeRunner

tasks = load_tasks(Path("eval/tasks"))
report = run_eval(
    tasks,
    ClaudeCodeRunner(),
    fixture_dir=Path("eval/fixtures/library_api"),
    trials=5,
    opendream_md=Path("AGENTS.md"),
)
print(f"baseline: {report.success_rate('baseline'):.0%}")
print(f"dreamed : {report.success_rate('dreamed'):.0%}")
print(f"lift    : {report.lift_pp():+.1f}pp")
```
"""

from __future__ import annotations

import importlib.util
import shutil
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class EvalTask:
    """A single eval task: a directory containing README, expected_test, score."""

    task_id: str
    task_dir: Path
    timeout_seconds: int = 120

    @property
    def prompt(self) -> str:
        return (self.task_dir / "README.md").read_text(encoding="utf-8")

    @property
    def expected_test_path(self) -> Path:
        return self.task_dir / "expected_test.py"

    def score(self, workspace: Path) -> bool:
        """Import this task's score.py and run its `score(workspace)` function."""
        score_file = self.task_dir / "score.py"
        spec = importlib.util.spec_from_file_location(
            f"opendream_eval_task_{self.task_id}", score_file
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"could not load {score_file}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return bool(module.score(workspace))


@dataclass
class TrialResult:
    task_id: str
    condition: str  # "baseline" | "dreamed"
    trial: int
    success: bool
    duration_s: float
    notes: str = ""


@dataclass
class EvalReport:
    trials: list[TrialResult] = field(default_factory=list)

    def success_rate(self, condition: str) -> float:
        rows = [t for t in self.trials if t.condition == condition]
        if not rows:
            return 0.0
        return statistics.fmean(1.0 if t.success else 0.0 for t in rows)

    def lift_pp(self) -> float:
        """Dreamed minus baseline, expressed in percentage points."""
        return (self.success_rate("dreamed") - self.success_rate("baseline")) * 100

    def per_task(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for cond in ("baseline", "dreamed"):
            for t in self.trials:
                if t.condition != cond:
                    continue
                out.setdefault(t.task_id, {}).setdefault(cond, 0.0)
        for task_id in out:
            for cond in ("baseline", "dreamed"):
                rows = [
                    t
                    for t in self.trials
                    if t.task_id == task_id and t.condition == cond
                ]
                if rows:
                    out[task_id][cond] = statistics.fmean(
                        1.0 if t.success else 0.0 for t in rows
                    )
        return out


class AgentRunner(Protocol):
    """Anything that can drive an agent through one trial of one task.

    The runner receives a per-trial workspace already populated from the
    fixture and the task's expected_test.py, the user prompt, and (for the
    dreamed condition) the path to an `AGENTS.md` file. The return value is
    informational; success is decided by the task's `score()`.
    """

    def run(
        self,
        task: EvalTask,
        workspace: Path,
        opendream_md: Path | None,
    ) -> bool: ...


def run_eval(
    tasks: list[EvalTask],
    runner: AgentRunner,
    fixture_dir: Path,
    *,
    trials: int = 5,
    opendream_md: Path | None = None,
    workdir: Path | None = None,
) -> EvalReport:
    """Run each task under both conditions, `trials` times each."""
    fixture_dir = Path(fixture_dir).resolve()
    workdir = (workdir or Path(".opendream-eval")).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    report = EvalReport()
    for task in tasks:
        for cond in ("baseline", "dreamed"):
            md = opendream_md if cond == "dreamed" else None
            for trial in range(trials):
                trial_dir = workdir / task.task_id / cond / f"trial-{trial}"
                if trial_dir.exists():
                    shutil.rmtree(trial_dir)
                shutil.copytree(fixture_dir, trial_dir)

                # Drop the task's expected_test.py into workspace/tests/ so
                # the score function (which usually runs pytest on it) finds it.
                if task.expected_test_path.exists():
                    tests_dir = trial_dir / "tests"
                    tests_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy(
                        task.expected_test_path,
                        tests_dir / f"test_{task.task_id}.py",
                    )

                start = time.perf_counter()
                try:
                    runner.run(task, trial_dir, md)
                    success = task.score(trial_dir)
                    notes = ""
                except Exception as exc:  # agent crashed; counts as failure
                    success = False
                    notes = f"agent exception: {exc!r}"
                duration = time.perf_counter() - start

                report.trials.append(
                    TrialResult(
                        task_id=task.task_id,
                        condition=cond,
                        trial=trial,
                        success=success,
                        duration_s=duration,
                        notes=notes,
                    )
                )
    return report


def load_tasks(tasks_dir: Path | str) -> list[EvalTask]:
    """Load tasks from `eval/tasks/<n>_<slug>/` directories.

    A directory is recognized as a task if it contains a `README.md` and a
    `score.py`. `expected_test.py` is optional (refactor tasks may not need it).
    """
    tasks_dir = Path(tasks_dir)
    tasks: list[EvalTask] = []
    for sub in sorted(tasks_dir.iterdir()):
        if not sub.is_dir():
            continue
        if not (sub / "README.md").exists() or not (sub / "score.py").exists():
            continue
        tasks.append(EvalTask(task_id=sub.name, task_dir=sub))
    return tasks
