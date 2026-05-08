# Reject loans created with a past due date

`POST /loans` currently accepts any `due_on` value, including dates in the
past (or today). A loan whose due date is already in the past is invalid
on creation — the lender would never accept it.

A failing test has been added at
`tests/test_03_loan_due_date_validation.py` that demonstrates the bug.
Make it pass.

The rejection should happen at request validation (HTTP 422), before any
service-layer logic runs. Existing valid-loan tests must keep passing.
