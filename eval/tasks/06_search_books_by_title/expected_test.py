from __future__ import annotations


def _seed_books(client) -> None:
    for i, title in enumerate(["Domain-Driven Design", "Domain Modelling Made Functional", "Clean Code", "Designing Data-Intensive Applications"]):
        client.post(
            "/books",
            json={"title": title, "author": "X", "isbn": f"978-0-13-{i:06d}-1"},
        )


def test_title_prefix_filter_matches_case_insensitively(client):
    _seed_books(client)
    r = client.get("/books", params={"title_prefix": "domain"})
    assert r.status_code == 200, r.text
    titles = sorted(b["title"] for b in r.json())
    assert titles == [
        "Domain Modelling Made Functional",
        "Domain-Driven Design",
    ]


def test_title_prefix_filter_returns_empty_when_no_match(client):
    _seed_books(client)
    r = client.get("/books", params={"title_prefix": "ZZZZ"})
    assert r.status_code == 200
    assert r.json() == []


def test_no_filter_still_returns_all_books(client):
    _seed_books(client)
    r = client.get("/books")
    assert r.status_code == 200
    assert len(r.json()) == 4


def test_only_available_filter_still_works(client):
    _seed_books(client)
    r = client.get("/books", params={"only_available": True})
    assert r.status_code == 200
    assert len(r.json()) == 4  # nothing on loan yet
