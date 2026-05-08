# Add tests for the HTTP error translator

The `translate(...)` helper in `app/api/_http_errors.py` is used by every
route to convert service-layer `Result` objects into HTTP responses, but
has no direct unit tests of its own — it's only exercised indirectly
through the API tests.

Write direct unit tests at `tests/test_translate.py` covering at least:

1. `Ok(value)` returns the value unchanged.
2. `Err(<known code>, <message>)` raises `HTTPException` with the right
   status code mapped from `_STATUS_MAP` (cover at least one 404 case
   and one 409 case).
3. The raised `HTTPException.detail` is a dict containing both `code`
   and `message`.
4. `Err(<unknown code>, ...)` falls back to status 500.

Use plain pytest with imports from the project — no FastAPI test client
needed; these are pure unit tests on `translate(...)`.

The test file must contain **at least 4 passing tests**.
