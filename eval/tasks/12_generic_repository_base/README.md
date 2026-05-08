# Refactor: introduce a generic Repository[T] base

The three resource repositories (`books`, `members`, `loans`) duplicate
identical machinery: a module-level dict, an `_NEXT_ID` counter, a
`reset()` test helper, and `find_by_id` / `save` / `delete_by_id` shapes.

Add a `Repository[T]` base in `app/repositories/_base.py` (note the
leading underscore — it's an internal abstraction) that captures this
shared shape, and migrate each of the three resource repos to use it.
Resource-specific lookup functions (`find_book_by_isbn`,
`find_member_by_email`, `find_active_loan_for_book`,
`find_loans_for_member`) stay in their respective modules.

Constraints:
- Public function names exposed by each repo module are unchanged
  (`find_book_by_id`, `save_book`, `delete_book_by_id`, etc.). Service
  code keeps importing the same names from the same modules.
- All existing tests stay green. No new tests required.
- `reset()` per module continues to work (tests' autouse fixture relies
  on it).
