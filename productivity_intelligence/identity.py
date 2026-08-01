"""Verified request identity and tenant context.

Identity Platform ID tokens are verified at the HTTP boundary. Downstream tools
read only this ContextVar; tenant identifiers are never model-controlled tool
arguments.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Iterator, Mapping

import google.auth.transport.requests
from fastapi import Request
from fastapi.responses import JSONResponse
from google.auth.exceptions import GoogleAuthError
from google.oauth2 import id_token
from starlette.concurrency import run_in_threadpool

from productivity_intelligence.config import settings
from productivity_intelligence.membership import (
    MembershipDeniedError,
    MembershipUnavailableError,
    membership_store,
)

LOGGER = logging.getLogger(__name__)
SUBJECT_NAMESPACE = uuid.UUID("2ea7b872-6bc4-4a37-9a58-75fd18d94086")


@dataclass(frozen=True)
class RequestIdentity:
    """Server-trusted identity propagated for one request."""

    tenant_id: uuid.UUID
    subject_id: uuid.UUID
    external_subject: str
    issuer: str
    role: str


_current_identity: ContextVar[RequestIdentity | None] = ContextVar(
    "request_identity", default=None
)


def derive_subject_id(issuer: str, external_subject: str) -> uuid.UUID:
    """Return a stable, non-reversible internal identifier for an IdP subject."""

    return uuid.uuid5(SUBJECT_NAMESPACE, f"{issuer}\x1f{external_subject}")


def _uuid_claim(value: Any, claim_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError(f"{claim_name} must be a UUID") from error


class IdentityTokenVerifier:
    """Verify Firebase/Identity Platform JWTs using Google's rotating keys."""

    def __init__(self) -> None:
        self._request = google.auth.transport.requests.Request()

    def verify(self, token: str) -> RequestIdentity:
        claims = id_token.verify_firebase_token(
            token,
            self._request,
            audience=settings.identity_platform_project_id,
            clock_skew_in_seconds=settings.auth_clock_skew_seconds,
        )
        expected_issuer = (
            f"https://securetoken.google.com/{settings.identity_platform_project_id}"
        )
        if claims.get("iss") != expected_issuer:
            raise ValueError("token issuer is invalid")
        external_subject = claims.get("sub")
        if (
            not isinstance(external_subject, str)
            or not external_subject
            or len(external_subject) > 128
        ):
            raise ValueError("token subject is invalid")

        firebase_claim = claims.get("firebase")
        if settings.identity_platform_tenant_id:
            if not isinstance(firebase_claim, Mapping):
                raise ValueError("token tenant is missing")
            if firebase_claim.get("tenant") != settings.identity_platform_tenant_id:
                raise ValueError("token belongs to an unauthorized Identity Platform tenant")

        tenant_value = claims.get(settings.identity_tenant_claim)
        if tenant_value is None:
            raise ValueError("identity tenant claim is missing")
        tenant_id = _uuid_claim(tenant_value, settings.identity_tenant_claim)
        return RequestIdentity(
            tenant_id=tenant_id,
            subject_id=derive_subject_id(expected_issuer, external_subject),
            external_subject=external_subject,
            issuer=expected_issuer,
            # Token roles can be stale after an administrative change. The
            # authoritative database membership replaces this placeholder
            # before any protected route runs.
            role="member",
        )


_verifier = IdentityTokenVerifier()


def require_identity() -> RequestIdentity:
    identity = _current_identity.get()
    if identity is None:
        raise RuntimeError("No verified request identity is available")
    return identity


def current_tenant_id() -> str:
    return str(require_identity().tenant_id)


def current_subject_id() -> str:
    return str(require_identity().subject_id)


def current_subject_token() -> str:
    """Return a keyed, non-reversible analytics subject token."""

    subject_id = str(require_identity().subject_id).encode("utf-8")
    return hmac.new(
        settings.pseudonymization_key.encode("utf-8"),
        subject_id,
        hashlib.sha256,
    ).hexdigest()


@contextmanager
def identity_scope(identity: RequestIdentity) -> Iterator[None]:
    """Install identity for tests and trusted non-HTTP orchestration."""

    token = _current_identity.set(identity)
    try:
        yield
    finally:
        _current_identity.reset(token)


def _demo_identity() -> RequestIdentity:
    return RequestIdentity(
        tenant_id=settings.default_tenant_id,
        subject_id=settings.demo_subject_id,
        external_subject="local-demo",
        issuer="urn:productivity-intelligence:local-demo",
        role="owner",
    )


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        {"error": "unauthorized", "message": "A valid sign-in token is required."},
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(message: str) -> JSONResponse:
    return JSONResponse(
        {"error": "forbidden", "message": message},
        status_code=403,
    )


def _membership_unavailable() -> JSONResponse:
    return JSONResponse(
        {
            "error": "service_unavailable",
            "message": "Tenant authorization is temporarily unavailable.",
        },
        status_code=503,
        headers={"Retry-After": "5"},
    )


async def identity_middleware(request: Request, call_next):
    """Authenticate protected routes and install their trusted tenant context."""

    if request.url.path in {"/healthz", "/readyz"}:
        return await call_next(request)

    if settings.auth_mode == "disabled":
        identity = _demo_identity()
    else:
        authorization = request.headers.get("authorization", "")
        scheme, _, credential = authorization.partition(" ")
        if scheme.lower() != "bearer" or not credential:
            return _unauthorized()
        try:
            identity = _verifier.verify(credential)
        except (GoogleAuthError, ValueError, TypeError):
            # Never expose token contents or verification internals.
            LOGGER.info(
                "Rejected invalid Identity Platform token",
                extra={
                    "security_event": "authentication_failed",
                    "token_fingerprint": hashlib.sha256(
                        credential.encode("utf-8")
                    ).hexdigest()[:12],
                },
            )
            return _unauthorized()
        try:
            authoritative_role = await run_in_threadpool(
                membership_store.authorize,
                tenant_id=identity.tenant_id,
                subject_id=identity.subject_id,
                issuer=identity.issuer,
                external_subject=identity.external_subject,
            )
            identity = replace(identity, role=authoritative_role)
        except MembershipDeniedError:
            LOGGER.info(
                "Rejected inactive tenant membership",
                extra={
                    "security_event": "membership_denied",
                    "tenant_id": str(identity.tenant_id),
                    "subject_id": str(identity.subject_id),
                },
            )
            return _forbidden("No active membership exists for this tenant.")
        except MembershipUnavailableError:
            LOGGER.warning(
                "Membership verification dependency unavailable",
                extra={"security_event": "membership_verification_failed"},
            )
            return _membership_unavailable()

    context_token = _current_identity.set(identity)
    try:
        request.state.identity = identity
        if settings.auth_mode == "identity_platform":
            user_match = re.search(r"/users/([^/]+)(?:/|$)", request.url.path)
            if user_match and user_match.group(1) != str(identity.subject_id):
                return _forbidden("The requested user scope is not authorized.")
            if request.url.path in {"/run", "/run_sse"}:
                try:
                    payload = await request.json()
                except ValueError:
                    return _forbidden("A valid request body is required.")
                requested_user = payload.get("user_id", payload.get("userId"))
                if requested_user != str(identity.subject_id):
                    return _forbidden("The requested user scope is not authorized.")
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response
    finally:
        _current_identity.reset(context_token)
