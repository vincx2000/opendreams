# Add: search books by title prefix

Add a `?title_prefix=<string>` query parameter to `GET /books`. When set,
the response should be the subset of books whose `title` starts with the
given prefix, case-insensitively. When unset, behavior is unchanged.

A test has been added at `tests/test_06_search_books_by_title.py` that
exercises the new behavior. Make it pass.

The existing `?only_available=` parameter and all current book endpoints
must keep working.
