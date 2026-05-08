from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "bad_isbn",
    [
        "----------",       # ten dashes, no digits
        "-------------",    # thirteen dashes
        "----123----",      # mostly dashes, only 3 digits
        "0--1--2--3--",     # only 4 digits
    ],
)
def test_isbn_must_contain_at_least_10_digits(client, bad_isbn):
    payload = {"title": "T", "author": "A", "isbn": bad_isbn}
    r = client.post("/books", json=payload)
    assert r.status_code == 422, (
        f"ISBN {bad_isbn!r} (insufficient digits) should be rejected; "
        f"got {r.status_code} {r.text}"
    )


def test_well_formed_isbn_with_hyphens_still_accepted(client):
    payload = {
        "title": "T",
        "author": "A",
        "isbn": "978-0-13-468599-1",
    }
    r = client.post("/books", json=payload)
    assert r.status_code == 201, r.text


def test_well_formed_isbn_without_hyphens_still_accepted(client):
    payload = {
        "title": "T2",
        "author": "A",
        "isbn": "0321583191",
    }
    r = client.post("/books", json=payload)
    assert r.status_code == 201, r.text
