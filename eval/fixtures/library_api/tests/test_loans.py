from __future__ import annotations

from datetime import date, timedelta


def _seed_book_and_member(client) -> tuple[int, int]:
    b = client.post(
        "/books",
        json={"title": "T", "author": "A", "isbn": "978-0-13-468599-1"},
    ).json()
    m = client.post(
        "/members", json={"name": "Ada", "email": "ada@example.com"}
    ).json()
    return b["id"], m["id"]


def _due() -> str:
    return (date.today() + timedelta(days=14)).isoformat()


def test_create_loan_marks_book_unavailable(client):
    bid, mid = _seed_book_and_member(client)
    r = client.post(
        "/loans", json={"book_id": bid, "member_id": mid, "due_on": _due()}
    )
    assert r.status_code == 201, r.text
    assert client.get(f"/books/{bid}").json()["available"] is False


def test_create_loan_rejects_unknown_book(client):
    _, mid = _seed_book_and_member(client)
    r = client.post(
        "/loans", json={"book_id": 999, "member_id": mid, "due_on": _due()}
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "loan_book_not_found"


def test_create_loan_rejects_book_already_on_loan(client):
    bid, mid = _seed_book_and_member(client)
    client.post("/loans", json={"book_id": bid, "member_id": mid, "due_on": _due()})
    r = client.post(
        "/loans", json={"book_id": bid, "member_id": mid, "due_on": _due()}
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "loan_book_unavailable"


def test_return_loan_marks_book_available_again(client):
    bid, mid = _seed_book_and_member(client)
    loan = client.post(
        "/loans", json={"book_id": bid, "member_id": mid, "due_on": _due()}
    ).json()
    r = client.post(f"/loans/{loan['id']}/return")
    assert r.status_code == 200, r.text
    assert r.json()["returned_on"] == date.today().isoformat()
    assert client.get(f"/books/{bid}").json()["available"] is True


def test_return_already_returned_loan_is_409(client):
    bid, mid = _seed_book_and_member(client)
    loan = client.post(
        "/loans", json={"book_id": bid, "member_id": mid, "due_on": _due()}
    ).json()
    client.post(f"/loans/{loan['id']}/return")
    r = client.post(f"/loans/{loan['id']}/return")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "loan_already_returned"
