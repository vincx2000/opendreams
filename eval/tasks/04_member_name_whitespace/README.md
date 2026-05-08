# Reject members with empty or whitespace-only names

`POST /members` currently accepts any non-null string as `name`, including
empty strings and strings consisting only of whitespace. A member with an
empty name is meaningless.

A failing test has been added at `tests/test_04_member_name_whitespace.py`
that demonstrates the bug. Make it pass.

The rejection should happen via the existing service-layer error pathway
that the rest of the codebase uses for member-creation problems.
