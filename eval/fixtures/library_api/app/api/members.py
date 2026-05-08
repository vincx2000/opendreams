"""HTTP routes for members."""

from __future__ import annotations

from fastapi import APIRouter

from app.api._http_errors import translate
from app.models import Member, MemberCreate
from app.services import members as members_svc


router = APIRouter(prefix="/members", tags=["members"])


@router.get("", response_model=list[Member])
def route_get_members() -> list[Member]:
    return translate(members_svc.list_members_service())


@router.get("/{member_id}", response_model=Member)
def route_get_member(member_id: int) -> Member:
    return translate(members_svc.get_member_service(member_id))


@router.post("", response_model=Member, status_code=201)
def route_create_member(payload: MemberCreate) -> Member:
    return translate(members_svc.create_member_service(payload))
