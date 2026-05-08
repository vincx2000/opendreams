from __future__ import annotations


def test_create_and_fetch_member(client):
    r = client.post("/members", json={"name": "Ada", "email": "ada@example.com"})
    assert r.status_code == 201, r.text
    member = r.json()
    assert member["id"] >= 1
    r = client.get(f"/members/{member['id']}")
    assert r.status_code == 200
    assert r.json()["name"] == "Ada"


def test_get_member_returns_404_for_unknown_id(client):
    r = client.get("/members/999")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "member_not_found"


def test_duplicate_email_is_rejected(client):
    payload = {"name": "Ada", "email": "ada@example.com"}
    assert client.post("/members", json=payload).status_code == 201
    r = client.post("/members", json=payload)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "member_duplicate_email"
