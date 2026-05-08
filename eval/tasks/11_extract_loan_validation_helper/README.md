# Refactor: extract a loan-validation helper

`create_loan_service` has three sequential validation checks at the top of
its body (book exists, member exists, book available). Pull those checks
out into a dedicated private helper inside the same module. The public
function should become a short call to the helper plus the loan-creation
logic on success.

Constraints:
- Public function signature stays the same (`create_loan_service(payload)`).
- The Result returned on each failure path stays identical (same error
  code, same message format).
- The helper is module-private (leading underscore) — not part of the
  service's public surface.
- All existing tests stay green. No new tests required.
