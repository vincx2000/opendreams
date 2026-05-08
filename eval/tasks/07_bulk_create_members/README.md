# Add: bulk member creation

Add `POST /members/bulk` that accepts a payload of the form:

```json
{ "members": [ { "name": "...", "email": "..." }, ... ] }
```

and returns:

```json
{
  "inserted": [ Member, ... ],
  "rejected": [ { "input": { "name": ..., "email": ... },
                  "code": "<error code>",
                  "message": "..." }, ... ]
}
```

Per-row failures (duplicate email, malformed input) are collected into
`rejected` rather than failing the whole request. Successful members are
returned in `inserted`. Order in both lists matches the input order.

A test has been added at `tests/test_07_bulk_create_members.py`. Make it
pass without breaking the existing single-member endpoint.
