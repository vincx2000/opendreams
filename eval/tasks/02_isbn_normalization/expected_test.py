from __future__ import annotations


def test_duplicate_isbn_detection_ignores_hyphens(client):
    first = {
        "title": "The Mythical Man-Month",
        "author": "Brooks",
        "isbn": "978-0-13-468599-1",
    }
    r = client.post("/books", json=first)
    assert r.status_code == 201, r.text

    same_isbn_no_hyphens = {
        "title": "Mythical Man-Month (reissue)",
        "author": "Brooks",
        "isbn": "9780134685991",
    }
    r = client.post("/books", json=same_isbn_no_hyphens)
    assert r.status_code == 409, (
        "logically-identical ISBNs differing only in hyphenation should "
        f"be detected as duplicates; got {r.status_code} {r.text}"
    )
    assert r.json()["detail"]["code"] == "book_duplicate_isbn"


def test_isbn_with_different_hyphenation_still_blocked(client):
    payload_a = {"title": "A", "author": "X", "isbn": "0-321-58319-9"}
    payload_b = {"title": "B", "author": "X", "isbn": "0321583199"}
    assert client.post("/books", json=payload_a).status_code == 201
    assert client.post("/books", json=payload_b).status_code == 409
