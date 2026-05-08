from eval.scorers import pytest_passes_with_min_count


def score(workspace):
    return pytest_passes_with_min_count(
        workspace, "tests/test_create_member_service.py", min_passing=4
    )
