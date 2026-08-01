"""Authenticated tenant-membership administration HTTP contract."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from productivity_intelligence.config import settings
from productivity_intelligence.identity import RequestIdentity, derive_subject_id
from productivity_intelligence.membership import (
    MembershipConflictError,
    MembershipUnavailableError,
    membership_store,
)

TenantRole = Literal["owner", "admin", "member", "viewer"]
router = APIRouter(prefix="/api/tenant/members", tags=["tenant-membership"])


class ProvisionMemberRequest(BaseModel):
    external_subject: str = Field(min_length=1, max_length=128)
    role: TenantRole = "member"


class UpdateMemberRoleRequest(BaseModel):
    role: TenantRole


def _administrator(request: Request) -> RequestIdentity:
    if settings.auth_mode != "identity_platform":
        raise HTTPException(
            status_code=403,
            detail="Tenant administration requires authenticated identity mode.",
        )
    identity: RequestIdentity = request.state.identity
    if identity.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Tenant administration is forbidden.")
    return identity


def _call(operation, **parameters):
    try:
        return operation(**parameters)
    except MembershipConflictError as error:
        raise HTTPException(
            status_code=409,
            detail="The requested membership change conflicts with tenant policy.",
        ) from error
    except MembershipUnavailableError as error:
        raise HTTPException(
            status_code=503,
            detail="Tenant administration is temporarily unavailable.",
            headers={"Retry-After": "5"},
        ) from error


@router.get("")
def list_members(request: Request):
    identity = _administrator(request)
    return {
        "members": _call(
            membership_store.list_members,
            tenant_id=identity.tenant_id,
            actor_subject_id=identity.subject_id,
        )
    }


@router.post("", status_code=201)
def provision_member(payload: ProvisionMemberRequest, request: Request):
    identity = _administrator(request)
    external_subject = payload.external_subject.strip()
    if not external_subject:
        raise HTTPException(status_code=422, detail="external_subject cannot be blank")
    target_subject_id = derive_subject_id(identity.issuer, external_subject)
    return _call(
        membership_store.provision_member,
        tenant_id=identity.tenant_id,
        actor_subject_id=identity.subject_id,
        target_subject_id=target_subject_id,
        issuer=identity.issuer,
        external_subject=external_subject,
        role=payload.role,
    )


@router.patch("/{subject_id}")
def update_member_role(
    subject_id: uuid.UUID,
    payload: UpdateMemberRoleRequest,
    request: Request,
):
    identity = _administrator(request)
    return _call(
        membership_store.update_role,
        tenant_id=identity.tenant_id,
        actor_subject_id=identity.subject_id,
        target_subject_id=subject_id,
        role=payload.role,
    )


@router.delete("/{subject_id}")
def revoke_member(
    subject_id: uuid.UUID,
    request: Request,
    confirm: Annotated[bool, Query(description="Explicit revocation confirmation")] = False,
):
    if not confirm:
        raise HTTPException(
            status_code=409,
            detail="Set confirm=true to revoke this membership.",
        )
    identity = _administrator(request)
    return _call(
        membership_store.revoke_member,
        tenant_id=identity.tenant_id,
        actor_subject_id=identity.subject_id,
        target_subject_id=subject_id,
    )
