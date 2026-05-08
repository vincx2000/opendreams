# OpenDream eval harness

Compares an agent's success rate **with** and **without** the consolidated
`AGENTS.md` injected. SPEC.md §3 ship criterion 3 sets the bar:

> ≥ 5 percentage-point lift on a 15-task suite, 5 trials per task per condition.

## Layout

```
eval/
├── runner.py        # orchestration: tasks × conditions × trials → EvalReport
├── scorers.py       # shared score helpers (pytest_passes, all_tests_pass, …)
├── agents.py        # AgentRunner implementations (ClaudeCodeRunner, AiderRunner)
├── fixtures/
│   └── library_api/ # the codebase under test (FastAPI book-lending service)
└── tasks/           # 15 tasks
    ├── 01_email_case_sensitivity/
    │   ├── README.md          # the prompt the agent sees
    │   ├── expected_test.py   # dropped into workspace/tests/ before agent runs
    │   └── score.py           # def score(workspace) -> bool
    ├── 02_isbn_normalization/
    ├── …
    └── 15_test_create_member_service/
```

## Task structure

Each task is a directory with three files:

- **`README.md`** — the prompt handed to the agent.
- **`expected_test.py`** — *(optional)* a test that drops into
  `workspace/tests/test_<task_id>.py` before the agent runs. For bug-fix
  and feature tasks, this is the test the agent must make pass. For
  refactor tasks (no expected_test) and test-addition tasks (the agent
  writes their own test files), it's omitted.
- **`score.py`** — exposes `def score(workspace: Path) -> bool`. Most
  scorers are one-liners delegating to `eval.scorers`.

## Task suite

Cross-task signal is deliberate. Tasks 01–05 introduce the codebase's
conventions (layered access, `Result[T]` wrapper, naming patterns,
domain-error enums) through the act of bug-fixing. Tasks 06–15 reuse
those conventions implicitly. OpenDream's consolidated memory should
capture the conventions across the early tasks and help the agent stay
consistent on the later ones — that's where the lift comes from.

| #  | Slug                            | Type           | Score logic                          |
| -- | ------------------------------- | -------------- | ------------------------------------ |
| 01 | `email_case_sensitivity`        | bug fix        | task-specific test passes            |
| 02 | `isbn_normalization`            | bug fix        | task-specific test passes            |
| 03 | `loan_due_date_validation`      | bug fix        | task-specific test passes            |
| 04 | `member_name_whitespace`        | bug fix        | task-specific test passes            |
| 05 | `isbn_regex_too_loose`          | bug fix        | task-specific test passes            |
| 06 | `search_books_by_title`         | feature        | task-specific test passes            |
| 07 | `bulk_create_members`           | feature        | task-specific test passes            |
| 08 | `cancel_loan`                   | feature        | task-specific test passes            |
| 09 | `member_loan_history`           | feature        | task-specific test passes            |
| 10 | `popular_books`                 | feature        | task-specific test passes            |
| 11 | `extract_loan_validation_helper`| refactor       | full suite stays green               |
| 12 | `generic_repository_base`       | refactor       | full suite stays green               |
| 13 | `typed_storage_dataclass`       | refactor       | full suite stays green               |
| 14 | `test_translate_function`       | test addition  | agent writes ≥4 passing tests        |
| 15 | `test_create_member_service`    | test addition  | agent writes ≥4 passing tests        |

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
    opendream_md=Path("AGENTS.md"),  # None for baseline-only
)
print(f"baseline: {report.success_rate('baseline'):.0%}")
print(f"dreamed : {report.success_rate('dreamed'):.0%}")
print(f"lift    : {report.lift_pp():+.1f}pp")
```

A CLI wrapper (`opendream eval run`) is wired alongside the rest of the
v0 commands once the runner is exercised against a real `claude` CLI.
