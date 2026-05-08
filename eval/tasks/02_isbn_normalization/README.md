# Reject duplicate ISBNs regardless of hyphenation

ISBNs are the same book whether written as `978-0-13-468599-1` or
`9780134685991` — they're just different formattings of the same number.
The duplicate-detection logic currently treats them as different.

A failing test has been added at `tests/test_02_isbn_normalization.py`
that demonstrates the bug. Make it pass.

The visible API for ISBNs (what the user POSTs and what comes back from
GET) does not need to change — only the internal duplicate check.
