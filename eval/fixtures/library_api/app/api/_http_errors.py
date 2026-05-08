"""
Map domain `Result.Err` codes to HTTP status codes. Routes call `translate(...)`
on every service Result; Ok returns the value unchanged, Err raises HTTPException.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.errors import BookError, LoanError, MemberError
from app.result import Result


_STATUS_MAP: dict[str, int] = {
    BookError.NOT_FOUND.value: 404,
    BookError.DUPLICATE_ISBN.value: 409,
    MemberError.NOT_FOUND.value: 404,
    MemberError.DUPLICATE_EMAIL.value: 409,
    LoanError.NOT_FOUND.value: 404,
    LoanError.BOOK_NOT_FOUND.value: 404,
    LoanError.MEMBER_NOT_FOUND.value: 404,
    LoanError.BOOK_UNAVAILABLE.value: 409,
    LoanError.ALREADY_RETURNED.value: 409,
}


def translate(result: Result):
    """Return result.value on Ok; raise HTTPException on Err."""
    if result.is_ok:
        return result.value
    status = _STATUS_MAP.get(result.code or "", 500)
    raise HTTPException(
        status_code=status,
        detail={"code": result.code, "message": result.message},
    )
