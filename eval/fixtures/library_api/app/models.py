"""
app.models
----------

Pydantic models for both DB-side state and HTTP request/response shapes.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class Book(BaseModel):
    id: int
    title: str
    author: str
    isbn: str
    available: bool = True


class BookCreate(BaseModel):
    title: str
    author: str
    isbn: str = Field(..., pattern=r"^[0-9\-]{10,17}$")


class Member(BaseModel):
    id: int
    name: str
    email: EmailStr


class MemberCreate(BaseModel):
    name: str
    email: EmailStr


class Loan(BaseModel):
    id: int
    book_id: int
    member_id: int
    loaned_on: date
    due_on: date
    returned_on: Optional[date] = None

    @property
    def is_active(self) -> bool:
        return self.returned_on is None


class LoanCreate(BaseModel):
    book_id: int
    member_id: int
    due_on: date
