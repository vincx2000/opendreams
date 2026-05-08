from __future__ import annotations


def test_empty_name_is_rejected(client):
    r = client.post("/members", json={"name": "", "email": "a@example.com"})
    assert r.status_code in (400, 409, 422), (
        f"empty name should be rejected; got {r.status_code} {r.text}"
    )


def test_whitespace_only_name_is_rejected(client):
    r = client.post("/members", json={"name": "   ", "email": "b@example.com"})
    assert r.status_code in (400, 409, 422), (
        f"whitespace-only name should be rejected; got {r.status_code} {r.text}"
    )


def test_name_with_surrounding_whitespace_is_accepted_or_trimmed(client):
    r = client.post(
        "/members", json={"name": "  Ada  ", "email": "c@example.com"}
    )
    # Either reject 4xx or accept-and-trim (200/201). Both are reasonable
    # fixes; we just shouldn't end up with a stored name that's literally
    # "  Ada  " with the spaces preserved.
    if r.status_code == 201:
        body = r.json()
        assert body["name"] == "Ada", (
            f"if accepted, surrounding whitespace must be trimmed; got {body!r}"
        )
    else:
        assert r.status_code in (400, 422)


def test_normal_name_still_accepted(client):
    r = client.post("/members", json={"name": "Ada", "email": "d@example.com"})
    assert r.status_code == 201, r.text
