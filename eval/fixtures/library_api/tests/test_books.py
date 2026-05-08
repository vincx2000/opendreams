from __future__ import annotations


def _book_payload(isbn: str = "978-0-13-468599-1") -> dict:
    return {"title": "The Mythical Man-Month", "author": "Brooks", "isbn": isbn}


def test_create_book_returns_201_and_marks_available(client):
    r = client.post("/books", json=_book_payload())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["available"] is True
    assert body["id"] >= 1


def test_get_book_returns_404_for_unknown_id(client):
    r = client.get("/books/999")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "book_not_found"


def test_create_book_rejects_duplicate_isbn(client):
    payload = _book_payload()
    assert client.post("/books", json=payload).status_code == 201
    r = client.post("/books", json=payload)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "book_duplicate_isbn"


def test_list_books_returns_all_inserted(client):
    client.post("/books", json=_book_payload(isbn="978-0-13-468599-1"))
    client.post("/books", json=_book_payload(isbn="978-0-201-89683-1"))
    r = client.get("/books")
    assert r.status_code == 200
    assert len(r.json()) == 2
