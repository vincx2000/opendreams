"""Loan business logic. Returns Result[T]."""

from __future__ import annotations

from datetime import date

from app.errors import LoanError
from app.models import Loan, LoanCreate
from app.repositories import books as books_repo
from app.repositories import loans as loans_repo
from app.repositories import members as members_repo
from app.result import Err, Ok, Result


def list_loans_service() -> Result[list[Loan]]:
    return Ok(loans_repo.list_loans())


def get_loan_service(loan_id: int) -> Result[Loan]:
    ln = loans_repo.find_loan_by_id(loan_id)
    if ln is None:
        return Err(LoanError.NOT_FOUND, f"loan {loan_id} not found")
    return Ok(ln)


def create_loan_service(payload: LoanCreate) -> Result[Loan]:
    book = books_repo.find_book_by_id(payload.book_id)
    if book is None:
        return Err(LoanError.BOOK_NOT_FOUND, f"book {payload.book_id} not found")

    member = members_repo.find_member_by_id(payload.member_id)
    if member is None:
        return Err(
            LoanError.MEMBER_NOT_FOUND, f"member {payload.member_id} not found"
        )

    if not book.available:
        return Err(
            LoanError.BOOK_UNAVAILABLE, f"book {book.id} is currently on loan"
        )

    book = book.model_copy(update={"available": False})
    books_repo.save_book(book)

    loan = Loan(
        id=0,
        book_id=book.id,
        member_id=member.id,
        loaned_on=date.today(),
        due_on=payload.due_on,
        returned_on=None,
    )
    return Ok(loans_repo.save_loan(loan))


def return_loan_service(loan_id: int) -> Result[Loan]:
    loan = loans_repo.find_loan_by_id(loan_id)
    if loan is None:
        return Err(LoanError.NOT_FOUND, f"loan {loan_id} not found")
    if not loan.is_active:
        return Err(
            LoanError.ALREADY_RETURNED, f"loan {loan_id} already returned"
        )

    loan = loan.model_copy(update={"returned_on": date.today()})
    loans_repo.save_loan(loan)

    book = books_repo.find_book_by_id(loan.book_id)
    if book is not None:
        books_repo.save_book(book.model_copy(update={"available": True}))

    return Ok(loan)
