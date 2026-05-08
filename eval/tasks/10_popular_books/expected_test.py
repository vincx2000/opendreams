from __future__ import annotations

from datetime import date, timedelta


def _due() -> str:
    return (date.today() + timedelta(days=14)).isoformat()


def _setup(client):
    books = []
    for i in range(4):
        b = client.post(
            "/books",
            json={
                "title": f"B{i}",
                "author": "X",
                "isbn": f"978-0-13-{i:06d}-1",
            },
        ).json()
        books.append(b)
    members = []
    for i in range(3):
        m = client.post(
            "/members", json={"name": f"M{i}", "email": f"m{i}@example.com"}
        ).json()
        members.append(m)
    return books, members


def _loan_and_return(client, book_id, member_id):
    loan = client.post(
        "/loans",
        json={"book_id": book_id, "member_id": member_id, "due_on": _due()},
    ).json()
    client.post(f"/loans/{loan['id']}/return")


def test_popular_returns_books_sorted_by_loan_count_desc(client):
    books, members = _setup(client)

    # B0: 3 loans, B1: 2 loans, B2: 1 loan, B3: 0 loans
    for m in members:
        _loan_and_return(client, books[0]["id"], m["id"])
    _loan_and_return(client, books[1]["id"], members[0]["id"])
    _loan_and_return(client, books[1]["id"], members[1]["id"])
    _loan_and_return(client, books[2]["id"], members[0]["id"])

    r = client.get("/books/popular")
    assert r.status_code == 200, r.text
    titles = [b["title"] for b in r.json()]
    assert titles == ["B0", "B1", "B2"]


def test_popular_excludes_zero_loan_books(client):
    books, members = _setup(client)
    _loan_and_return(client, books[0]["id"], members[0]["id"])

    r = client.get("/books/popular")
    titles = [b["title"] for b in r.json()]
    assert "B3" not in titles  # never loaned


def test_popular_respects_limit_query_param(client):
    books, members = _setup(client)
    _loan_and_return(client, books[0]["id"], members[0]["id"])
    _loan_and_return(client, books[1]["id"], members[0]["id"])
    _loan_and_return(client, books[2]["id"], members[0]["id"])

    r = client.get("/books/popular", params={"limit": 2})
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_popular_with_no_loans_returns_empty_list(client):
    _setup(client)
    r = client.get("/books/popular")
    assert r.status_code == 200
    assert r.json() == []
