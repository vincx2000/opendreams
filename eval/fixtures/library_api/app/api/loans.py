"""HTTP routes for loans."""

from __future__ import annotations

from fastapi import APIRouter

from app.api._http_errors import translate
from app.models import Loan, LoanCreate
from app.services import loans as loans_svc


router = APIRouter(prefix="/loans", tags=["loans"])


@router.get("", response_model=list[Loan])
def route_get_loans() -> list[Loan]:
    return translate(loans_svc.list_loans_service())


@router.get("/{loan_id}", response_model=Loan)
def route_get_loan(loan_id: int) -> Loan:
    return translate(loans_svc.get_loan_service(loan_id))


@router.post("", response_model=Loan, status_code=201)
def route_create_loan(payload: LoanCreate) -> Loan:
    return translate(loans_svc.create_loan_service(payload))


@router.post("/{loan_id}/return", response_model=Loan)
def route_return_loan(loan_id: int) -> Loan:
    return translate(loans_svc.return_loan_service(loan_id))
