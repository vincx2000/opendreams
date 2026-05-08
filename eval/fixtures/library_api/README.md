# library_api — eval fixture

Tiny FastAPI service for lending books to library members. It's small but
deliberately layered so the eval can measure whether memory consolidation
helps an agent stay consistent with the codebase's conventions.

## Layout

```
app/
├── main.py                 # FastAPI() + router mounting
├── models.py               # Pydantic request/response models
├── result.py               # Result[T] = Ok(value) | Err(code, message)
├── errors.py               # Per-resource Enum domain errors
├── api/                    # HTTP layer — routes, error translation
│   ├── _http_errors.py
│   ├── books.py
│   ├── members.py
│   └── loans.py
├── services/               # Business logic. Returns Result[T].
│   ├── books.py
│   ├── members.py
│   └── loans.py
└── repositories/           # In-memory storage. No business logic.
    ├── books.py
    ├── members.py
    └── loans.py
tests/
├── conftest.py
├── test_books.py
├── test_members.py
└── test_loans.py
```

## Conventions

These are load-bearing — eval tasks rely on them being uniform.

1. **Layered access.** Routes call services; services call repositories.
   Routes never touch a repository directly. If a route needs data, it asks
   a service.

2. **Result wrapper.** Services do not raise on expected failure paths;
   they return `Result[T] = Ok(value) | Err(code, message)`. Routes use
   `app.api._http_errors.translate(result)` to map `Err` → `HTTPException`.

3. **Naming.**
   - Route handlers: `route_<verb>_<resource>` (e.g. `route_get_books`).
   - Service entry points: `<verb>_<resource>_service` (e.g. `list_books_service`).
   - Repository functions: `find_<resource>_by_<field>`, `save_<resource>`,
     `delete_<resource>_by_id`.

4. **Errors.** Each resource has its own `Enum` (`BookError`, `MemberError`,
   `LoanError`); members are stable string codes that the HTTP translator
   can map to status codes.

5. **No async.** All endpoints and service functions are sync. Don't add
   `async def` without a real reason.

## Running

```bash
pip install -e .[dev]
pytest -q
uvicorn app.main:app --reload
```
