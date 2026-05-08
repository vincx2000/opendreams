from __future__ import annotations


def test_member_lookup_by_email_is_case_insensitive(client):
    payload = {"name": "Ada", "email": "ada@example.com"}
    created = client.post("/members", json=payload).json()
    assert created["email"].lower() == "ada@example.com"

    # Re-registering with a differently-cased email should be rejected as
    # a duplicate (this is what fails today — the lookup is exact-match).
    duplicate = {"name": "Ada Lovelace", "email": "ADA@example.com"}
    r = client.post("/members", json=duplicate)
    assert r.status_code == 409, (
        "duplicate-email check should be case-insensitive; "
        f"got {r.status_code} {r.text}"
    )
    assert r.json()["detail"]["code"] == "member_duplicate_email"
