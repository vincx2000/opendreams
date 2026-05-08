"""Book business logic. Returns Result[T]; never raises on expected failures."""

from __future__ import annotations

from app.errors import BookError
from app.models import Book, BookCreate
from app.repositories import books as books_repo
from app.result import Err, Ok, Result


def list_books_service() -> Result[list[Book]]:
    return Ok(books_repo.list_books())


def get_book_service(book_id: int) -> Result[Book]:
    book = books_repo.find_book_by_id(book_id)
    if book is None:
        return Err(BookError.NOT_FOUND, f"book {book_id} not found")
    return Ok(book)


def create_book_service(payload: BookCreate) -> Result[Book]:
    if books_repo.find_book_by_isbn(payload.isbn) is not None:
        return Err(BookError.DUPLICATE_ISBN, f"isbn {payload.isbn} already exists")
    book = Book(id=0, available=True, **payload.model_dump())
    return Ok(books_repo.save_book(book))


def list_available_books_service() -> Result[list[Book]]:
    return Ok([b for b in books_repo.list_books() if b.available])
