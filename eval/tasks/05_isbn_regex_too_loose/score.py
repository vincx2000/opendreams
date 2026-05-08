from eval.scorers import pytest_passes


def score(workspace):
    return pytest_passes(workspace, "tests/test_05_isbn_regex_too_loose.py")
