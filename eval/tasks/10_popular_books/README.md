# Add: most-borrowed books

Add `GET /books/popular` that returns books sorted by their total loan
count (active + returned) descending. Books with zero loans are not
returned. Ties are broken by `book.id` ascending.

Optional `?limit=N` query parameter caps the result length (default 10).

Each entry in the response is a regular `Book` object — the loan count
itself does NOT need to appear in the schema. Sorting is the visible
behavior.

A test has been added at `tests/test_10_popular_books.py`. Make it pass.
