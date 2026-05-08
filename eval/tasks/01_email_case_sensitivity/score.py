from eval.scorers import pytest_passes


def score(workspace):
    return pytest_passes(workspace, "tests/test_01_email_case_sensitivity.py")
