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


def test_loan_with_past_due_date_is_rejected_at_validation(client):
    bid, mid = _seed(client)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    r = client.post(
        "/loans", json={"book_id": bid, "member_id": mid, "due_on": yesterday}
    )
    assert r.status_code == 422, (
        f"past due_on should be rejected at validation; got {r.status_code} {r.text}"
    )


def test_loan_with_today_due_date_is_rejected(client):
    bid, mid = _seed(client)
    today = date.today().isoformat()
    r = client.post(
        "/loans", json={"book_id": bid, "member_id": mid, "due_on": today}
    )
    assert r.status_code == 422


def test_loan_with_future_due_date_is_still_accepted(client):
    bid, mid = _seed(client)
    future = (date.today() + timedelta(days=14)).isoformat()
    r = client.post(
        "/loans", json={"book_id": bid, "member_id": mid, "due_on": future}
    )
    assert r.status_code == 201, r.text
