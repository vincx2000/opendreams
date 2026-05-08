from eval.scorers import all_tests_pass


def score(workspace):
    return all_tests_pass(workspace)
