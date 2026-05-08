from __future__ import annotations

from datetime import date, timedelta


def _due() -> str:
    return (date.today() + timedelta(days=14)).isoformat()


def _seed(client):
    member = client.post(
        "/members", json={"name": "Ada", "email": "ada@example.com"}
    ).json()
    other = client.post(
        "/members", json={"name": "Grace", "email": "grace@example.com"}
    ).json()
    books = []
    for i in range(3):
        b = client.post(
            "/books",
            json={
                "title": f"Book {i}",
                "author": "X",
                "isbn": f"978-0-13-{i:06d}-1",
            },
        ).json()
        books.append(b)
    return member, other, books


def test_member_loan_history_returns_active_and_returned(client):
    member, _other, books = _seed(client)

    # Two loans for `member`, return the first
    l1 = client.post(
        "/loans",
        json={"book_id": books[0]["id"], "member_id": member["id"], "due_on": _due()},
    ).json()
    client.post(f"/loans/{l1['id']}/return")
    client.post(
        "/loans",
        json={"book_id": books[1]["id"], "member_id": member["id"], "due_on": _due()},
    )

    r = client.get(f"/members/{member['id']}/loans")
    assert r.status_code == 200, r.text
    history = r.json()
    assert len(history) == 2
    # Both loans returned, the first one having `returned_on` set
    returned = [ln for ln in history if ln["returned_on"] is not None]
    active = [ln for ln in history if ln["returned_on"] is None]
    assert len(returned) == 1
    assert len(active) == 1


def test_member_with_no_loans_returns_empty_list(client):
    member, _other, _books = _seed(client)
    r = client.get(f"/members/{member['id']}/loans")
    assert r.status_code == 200
    assert r.json() == []


def test_unknown_member_id_is_404(client):
    r = client.get("/members/999999/loans")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "member_not_found"


def test_history_does_not_include_other_members_loans(client):
    member, other, books = _seed(client)
    # Create a loan for `other`
    client.post(
        "/loans",
        json={"book_id": books[2]["id"], "member_id": other["id"], "due_on": _due()},
    )
    r = client.get(f"/members/{member['id']}/loans")
    assert r.status_code == 200
    assert r.json() == []
