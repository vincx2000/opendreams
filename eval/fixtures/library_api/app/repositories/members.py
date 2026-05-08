"""In-memory member storage."""

from __future__ import annotations

from itertools import count

from app.models import Member


_MEMBERS: dict[int, Member] = {}
_NEXT_ID = count(1)


def reset() -> None:
    _MEMBERS.clear()
    global _NEXT_ID
    _NEXT_ID = count(1)


def find_member_by_id(member_id: int) -> Member | None:
    return _MEMBERS.get(member_id)


def find_member_by_email(email: str) -> Member | None:
    for m in _MEMBERS.values():
        if m.email == email:
            return m
    return None


def list_members() -> list[Member]:
    return list(_MEMBERS.values())


def save_member(member: Member) -> Member:
    if member.id == 0:
        member = member.model_copy(update={"id": next(_NEXT_ID)})
    _MEMBERS[member.id] = member
    return member


def delete_member_by_id(member_id: int) -> bool:
    return _MEMBERS.pop(member_id, None) is not None
