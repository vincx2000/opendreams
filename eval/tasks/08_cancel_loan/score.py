from eval.scorers import pytest_passes


def score(workspace):
    return pytest_passes(workspace, "tests/test_08_cancel_loan.py")
