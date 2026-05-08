from eval.scorers import pytest_passes


def score(workspace):
    return pytest_passes(workspace, "tests/test_02_isbn_normalization.py")
