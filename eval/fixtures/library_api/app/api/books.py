"""HTTP routes for books. Handlers translate Result via _http_errors.translate."""

from __future__ import annotations

from fastapi import APIRouter

from app.api._http_errors import translate
from app.models import Book, BookCreate
from app.services import books as books_svc


router = APIRouter(prefix="/books", tags=["books"])


@router.get("", response_model=list[Book])
def route_get_books(only_available: bool = False) -> list[Book]:
    if only_available:
        return translate(books_svc.list_available_books_service())
    return translate(books_svc.list_books_service())


@router.get("/{book_id}", response_model=Book)
def route_get_book(book_id: int) -> Book:
    return translate(books_svc.get_book_service(book_id))


@router.post("", response_model=Book, status_code=201)
def route_create_book(payload: BookCreate) -> Book:
    return translate(books_svc.create_book_service(payload))
