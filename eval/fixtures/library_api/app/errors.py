"""
app.errors
----------

Per-resource domain error enums. Members are the stable string codes that
the HTTP translator in `app.api._http_errors` uses to pick a status.
"""

from __future__ import annotations

from enum import Enum


class BookError(str, Enum):
    NOT_FOUND = "book_not_found"
    DUPLICATE_ISBN = "book_duplicate_isbn"


class MemberError(str, Enum):
    NOT_FOUND = "member_not_found"
    DUPLICATE_EMAIL = "member_duplicate_email"


class LoanError(str, Enum):
    NOT_FOUND = "loan_not_found"
    BOOK_NOT_FOUND = "loan_book_not_found"
    MEMBER_NOT_FOUND = "loan_member_not_found"
    BOOK_UNAVAILABLE = "loan_book_unavailable"
    ALREADY_RETURNED = "loan_already_returned"
