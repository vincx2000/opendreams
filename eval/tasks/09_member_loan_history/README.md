# Add: full loan history for a member

Add `GET /members/{member_id}/loans` that returns all loans (active and
returned) belonging to that member, in `loaned_on` ascending order.

Edge cases:
- Member with no loans → `200 OK` with `[]`.
- Unknown member id → `404` with `member_not_found`.

A test has been added at `tests/test_09_member_loan_history.py`. Make it
pass.
