from __future__ import annotations

from datetime import date, timedelta


def _seed(client) -> tuple[int, int]:
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


def test_cancel_active_loan_restores_book_availability(client):
    bid, mid = _seed(client)
    loan = client.post(
        "/loans", json={"book_id": bid, "member_id": mid, "due_on": _due()}
    ).json()
    assert client.get(f"/books/{bid}").json()["available"] is False

    r = client.delete(f"/loans/{loan['id']}")
    assert r.status_code in (200, 204), r.text

    # Book should be available again
    assert client.get(f"/books/{bid}").json()["available"] is True
    # Loan should be gone from list
    listed_ids = {ln["id"] for ln in client.get("/loans").json()}
    assert loan["id"] not in listed_ids


def test_cancel_unknown_loan_is_404(client):
    r = client.delete("/loans/999999")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "loan_not_found"


def test_cancel_already_returned_loan_is_409(client):
    bid, mid = _seed(client)
    loan = client.post(
        "/loans", json={"book_id": bid, "member_id": mid, "due_on": _due()}
    ).json()
    # Return it normally first
    client.post(f"/loans/{loan['id']}/return")

    r = client.delete(f"/loans/{loan['id']}")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "loan_already_returned"


def test_existing_return_endpoint_still_works(client):
    bid, mid = _seed(client)
    loan = client.post(
        "/loans", json={"book_id": bid, "member_id": mid, "due_on": _due()}
    ).json()
    r = client.post(f"/loans/{loan['id']}/return")
    assert r.status_code == 200
    assert r.json()["returned_on"] == date.today().isoformat()
