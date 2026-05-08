"""Member business logic. Returns Result[T]."""

from __future__ import annotations

from app.errors import MemberError
from app.models import Member, MemberCreate
from app.repositories import members as members_repo
from app.result import Err, Ok, Result


def list_members_service() -> Result[list[Member]]:
    return Ok(members_repo.list_members())


def get_member_service(member_id: int) -> Result[Member]:
    m = members_repo.find_member_by_id(member_id)
    if m is None:
        return Err(MemberError.NOT_FOUND, f"member {member_id} not found")
    return Ok(m)


def create_member_service(payload: MemberCreate) -> Result[Member]:
    if members_repo.find_member_by_email(payload.email) is not None:
        return Err(
            MemberError.DUPLICATE_EMAIL,
            f"email {payload.email} already registered",
        )
    member = Member(id=0, **payload.model_dump())
    return Ok(members_repo.save_member(member))
