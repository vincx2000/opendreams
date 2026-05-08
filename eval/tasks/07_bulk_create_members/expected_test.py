from __future__ import annotations


def test_bulk_create_inserts_all_unique_members(client):
    payload = {
        "members": [
            {"name": "Ada", "email": "ada@example.com"},
            {"name": "Grace", "email": "grace@example.com"},
            {"name": "Linus", "email": "linus@example.com"},
        ]
    }
    r = client.post("/members/bulk", json=payload)
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert len(body["inserted"]) == 3
    assert body["rejected"] == []
    inserted_emails = {m["email"] for m in body["inserted"]}
    assert inserted_emails == {
        "ada@example.com",
        "grace@example.com",
        "linus@example.com",
    }


def test_bulk_create_collects_per_row_duplicates(client):
    # Pre-seed Ada
    client.post("/members", json={"name": "Ada", "email": "ada@example.com"})

    payload = {
        "members": [
            {"name": "Ada-2", "email": "ada@example.com"},
            {"name": "Grace", "email": "grace@example.com"},
        ]
    }
    r = client.post("/members/bulk", json=payload)
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert len(body["inserted"]) == 1
    assert body["inserted"][0]["email"] == "grace@example.com"
    assert len(body["rejected"]) == 1
    rejected = body["rejected"][0]
    assert rejected["input"]["email"] == "ada@example.com"
    assert rejected["code"] == "member_duplicate_email"


def test_bulk_create_preserves_input_order(client):
    payload = {
        "members": [
            {"name": f"User{i}", "email": f"u{i}@example.com"} for i in range(5)
        ]
    }
    r = client.post("/members/bulk", json=payload)
    body = r.json()
    inserted_emails = [m["email"] for m in body["inserted"]]
    assert inserted_emails == [f"u{i}@example.com" for i in range(5)]


def test_existing_single_endpoint_still_works(client):
    r = client.post("/members", json={"name": "Solo", "email": "solo@example.com"})
    assert r.status_code == 201
