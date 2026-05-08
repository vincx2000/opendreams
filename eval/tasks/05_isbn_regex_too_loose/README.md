# Tighten ISBN format validation

The current ISBN validator accepts strings that match `^[0-9\-]{10,17}$`,
which means `"----------"` (ten dashes, no digits) and similarly degenerate
strings pass through. A real ISBN must contain at least 10 digits.

A failing test has been added at `tests/test_05_isbn_regex_too_loose.py`
that demonstrates the bug. Make it pass.

The valid ISBN format checks (existing book-creation tests) must still
pass.
