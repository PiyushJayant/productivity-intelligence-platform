"""Authenticated, confirmation-gated privacy request API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from productivity_intelligence.identity import RequestIdentity
from productivity_intelligence.privacy import (
    PrivacyConflictError,
    PrivacyUnavailableError,
    privacy_store,
)

router = APIRouter(prefix="/api/privacy/erasure-requests", tags=["privacy"])


class ErasureRequest(BaseModel):
    subject_id: uuid.UUID | None = None
    confirmation: str


def _identity(request: Request) -> RequestIdentity:
    return request.state.identity


def _translate(operation, **parameters):
    try:
        return operation(**parameters)
    except PrivacyConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The erasure request conflicts with tenant policy.",
        ) from error
    except PrivacyUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Privacy request processing is temporarily unavailable.",
            headers={"Retry-After": "5"},
        ) from error


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def request_erasure(payload: ErasureRequest, request: Request):
    if payload.confirmation != "ERASE_SUBJECT_DATA":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Set confirmation to ERASE_SUBJECT_DATA to submit this request.",
        )
    identity = _identity(request)
    target = payload.subject_id or identity.subject_id
    return _translate(
        privacy_store.request_erasure,
        tenant_id=identity.tenant_id,
        actor_subject_id=identity.subject_id,
        target_subject_id=target,
    )


@router.get("")
def list_erasure_requests(request: Request):
    identity = _identity(request)
    return {
        "requests": _translate(
            privacy_store.list_erasure_requests,
            tenant_id=identity.tenant_id,
            actor_subject_id=identity.subject_id,
        )
    }
