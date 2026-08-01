from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from productivity_intelligence import identity


def test_subject_id_is_stable_and_issuer_scoped():
    first = identity.derive_subject_id("issuer-a", "user-1")
    assert first == identity.derive_subject_id("issuer-a", "user-1")
    assert first != identity.derive_subject_id("issuer-b", "user-1")


def test_identity_scope_fails_closed_and_resets():
    with pytest.raises(RuntimeError, match="No verified"):
        identity.require_identity()
    expected = identity.RequestIdentity(
        tenant_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        subject_id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
        external_subject="user",
        issuer="issuer",
        role="member",
    )
    with identity.identity_scope(expected):
        assert identity.current_tenant_id() == str(expected.tenant_id)
        assert identity.current_subject_id() == str(expected.subject_id)
    with pytest.raises(RuntimeError, match="No verified"):
        identity.require_identity()


def test_identity_platform_claims_are_strictly_validated(monkeypatch):
    project = identity.settings.identity_platform_project_id
    issuer = f"https://securetoken.google.com/{project}"
    claims = {
        "iss": issuer,
        "sub": "idp-user",
        "app_tenant_id": "11111111-1111-4111-8111-111111111111",
        "app_role": "admin",
    }
    monkeypatch.setattr(
        identity.id_token,
        "verify_firebase_token",
        lambda *_args, **_kwargs: claims,
    )
    actual = identity.IdentityTokenVerifier().verify("signed-token")
    assert actual.tenant_id == uuid.UUID(claims["app_tenant_id"])
    assert actual.subject_id == identity.derive_subject_id(issuer, "idp-user")
    assert actual.role == "admin"

    claims["iss"] = "https://attacker.example"
    with pytest.raises(ValueError, match="issuer"):
        identity.IdentityTokenVerifier().verify("signed-token")


def test_health_is_public_but_application_route_gets_demo_identity():
    app = FastAPI()
    app.middleware("http")(identity.identity_middleware)

    @app.get("/healthz")
    def health():
        return {"ok": True}

    @app.get("/protected")
    def protected():
        return {"tenant": identity.current_tenant_id()}

    client = TestClient(app)
    assert client.get("/healthz").status_code == 200
    response = client.get("/protected")
    assert response.status_code == 200
    assert response.json()["tenant"] == str(identity.settings.default_tenant_id)
    assert response.headers["cache-control"] == "no-store"


def test_identity_mode_rejects_missing_token_and_cross_user_scope(monkeypatch):
    configured = replace(
        identity.settings,
        auth_mode="identity_platform",
        identity_platform_project_id="test-project",
    )
    monkeypatch.setattr(identity, "settings", configured)
    expected = identity.RequestIdentity(
        tenant_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        subject_id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
        external_subject="user",
        issuer="https://securetoken.google.com/test-project",
        role="member",
    )
    monkeypatch.setattr(identity._verifier, "verify", lambda _token: expected)

    app = FastAPI()
    app.middleware("http")(identity.identity_middleware)

    @app.get("/apps/app/users/{user_id}/sessions")
    def sessions(user_id: str):
        return {"user_id": user_id}

    client = TestClient(app)
    assert client.get(
        f"/apps/app/users/{expected.subject_id}/sessions"
    ).status_code == 401
    headers = {"Authorization": "Bearer valid"}
    assert client.get(
        f"/apps/app/users/{expected.subject_id}/sessions", headers=headers
    ).status_code == 200
    assert client.get(
        "/apps/app/users/another-user/sessions", headers=headers
    ).status_code == 403
