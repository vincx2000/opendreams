# Add direct service-layer tests for create_member_service

`app/services/members.py::create_member_service` is currently only
exercised through the API layer. Add direct service-layer tests at
`tests/test_create_member_service.py` that bypass FastAPI and verify the
service's `Result` contract.

The test file must contain **at least 4 passing tests** covering:

1. Successful creation returns `Ok(member)` with `is_ok` true and a
   non-zero member id.
2. Duplicate email returns `Err(MemberError.DUPLICATE_EMAIL, ...)` with
   `is_err` true and the right error code.
3. The returned `Member` is also retrievable from the repository
   afterwards (i.e. the service actually persists it).
4. The `Result.message` field on a duplicate-email error mentions the
   email that conflicted.

Tests should call the service function directly, not the HTTP API. They
must reset the repository state between cases (the existing autouse
`_reset_state` fixture in `tests/conftest.py` already handles this if
your tests live alongside the others).
