from eval.scorers import pytest_passes


def score(workspace):
    return pytest_passes(workspace, "tests/test_07_bulk_create_members.py")
