"""In-memory loan storage."""

from __future__ import annotations

from itertools import count

from app.models import Loan


_LOANS: dict[int, Loan] = {}
_NEXT_ID = count(1)


def reset() -> None:
    _LOANS.clear()
    global _NEXT_ID
    _NEXT_ID = count(1)


def find_loan_by_id(loan_id: int) -> Loan | None:
    return _LOANS.get(loan_id)


def find_active_loan_for_book(book_id: int) -> Loan | None:
    for ln in _LOANS.values():
        if ln.book_id == book_id and ln.is_active:
            return ln
    return None


def find_loans_for_member(member_id: int) -> list[Loan]:
    return [ln for ln in _LOANS.values() if ln.member_id == member_id]


def list_loans() -> list[Loan]:
    return list(_LOANS.values())


def save_loan(loan: Loan) -> Loan:
    if loan.id == 0:
        loan = loan.model_copy(update={"id": next(_NEXT_ID)})
    _LOANS[loan.id] = loan
    return loan


def delete_loan_by_id(loan_id: int) -> bool:
    return _LOANS.pop(loan_id, None) is not None
