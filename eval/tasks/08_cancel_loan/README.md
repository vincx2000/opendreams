# Add: cancel an outstanding loan

Add `DELETE /loans/{loan_id}` that **cancels** an active loan. Cancelling
is distinct from returning:

- Returning records that the book came back (sets `returned_on`).
- Cancelling represents "the loan never really happened" — the loan is
  removed from the active set, the book is restored to available, but
  the loan record itself is deleted (not kept with a returned date).

Constraints:
- Only active (un-returned) loans can be cancelled. Cancelling an
  already-returned loan is a 409 conflict using the existing
  `loan_already_returned` error code.
- Cancelling a non-existent loan is 404 with `loan_not_found`.
- After successful cancellation, the book is `available: true` again.

A test has been added at `tests/test_08_cancel_loan.py`. Make it pass
without breaking the existing return endpoint.
