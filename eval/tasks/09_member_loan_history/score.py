from eval.scorers import pytest_passes


def score(workspace):
    return pytest_passes(workspace, "tests/test_09_member_loan_history.py")
