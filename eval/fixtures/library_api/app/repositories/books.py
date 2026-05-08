"""In-memory book storage. Repositories know nothing about HTTP or services."""

from __future__ import annotations

from itertools import count

from app.models import Book


_BOOKS: dict[int, Book] = {}
_NEXT_ID = count(1)


def reset() -> None:
    """Wipe the store. Test-only helper."""
    _BOOKS.clear()
    global _NEXT_ID
    _NEXT_ID = count(1)


def find_book_by_id(book_id: int) -> Book | None:
    return _BOOKS.get(book_id)


def find_book_by_isbn(isbn: str) -> Book | None:
    for b in _BOOKS.values():
        if b.isbn == isbn:
            return b
    return None


def list_books() -> list[Book]:
    return list(_BOOKS.values())


def save_book(book: Book) -> Book:
    if book.id == 0:
        book = book.model_copy(update={"id": next(_NEXT_ID)})
    _BOOKS[book.id] = book
    return book


def delete_book_by_id(book_id: int) -> bool:
    return _BOOKS.pop(book_id, None) is not None
