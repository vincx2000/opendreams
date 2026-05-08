# Fix the case-sensitivity bug in member email lookup

When a member is registered with email `ada@example.com` and someone tries
to look them up by `Ada@example.com` or `ADA@EXAMPLE.COM`, the lookup
returns nothing. Email lookups should be case-insensitive.

A failing test has been added at `tests/test_01_email_case_sensitivity.py`
that demonstrates the bug. Make it pass.
