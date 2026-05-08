from eval.scorers import pytest_passes


def score(workspace):
    return pytest_passes(workspace, "tests/test_04_member_name_whitespace.py")
