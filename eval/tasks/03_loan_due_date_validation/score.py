from eval.scorers import pytest_passes


def score(workspace):
    return pytest_passes(workspace, "tests/test_03_loan_due_date_validation.py")
