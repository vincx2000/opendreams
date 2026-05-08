from eval.scorers import pytest_passes


def score(workspace):
    return pytest_passes(workspace, "tests/test_06_search_books_by_title.py")
