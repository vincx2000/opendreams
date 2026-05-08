from eval.scorers import pytest_passes_with_min_count


def score(workspace):
    return pytest_passes_with_min_count(
        workspace, "tests/test_translate.py", min_passing=4
    )
