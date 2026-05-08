"""FastAPI app: just mounts the three resource routers."""

from __future__ import annotations

from fastapi import FastAPI

from app.api import books, loans, members


app = FastAPI(title="library_api")
app.include_router(books.router)
app.include_router(members.router)
app.include_router(loans.router)


@app.get("/health")
def route_health() -> dict[str, str]:
    return {"status": "ok"}
