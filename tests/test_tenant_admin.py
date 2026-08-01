from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from productivity_intelligence import tenant_admin
from productivity_intelligence.identity import RequestIdentity, derive_subject_id

TENANT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
ACTOR_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
TARGET_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


@pytest.fixture(autouse=True)
def identity_platform_mode(monkeypatch):
    monkeypatch.setattr(
        tenant_admin,
        "settings",
        replace(tenant_admin.settings, auth_mode="identity_platform"),
    )


def _client(role: str = "owner") -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def install_identity(request: Request, call_next):
        request.state.identity = RequestIdentity(
            tenant_id=TENANT_ID,
            subject_id=ACTOR_ID,
            external_subject="actor",
            issuer="https://securetoken.google.com/test-project",
            role=role,
        )
        return await call_next(request)

    app.include_router(tenant_admin.router)
    return TestClient(app)


def test_tenant_admin_is_disabled_without_identity_platform(monkeypatch):
    monkeypatch.setattr(
        tenant_admin,
        "settings",
        replace(tenant_admin.settings, auth_mode="disabled"),
    )
    assert _client().get("/api/tenant/members").status_code == 403


def test_member_provisioning_derives_target_and_never_accepts_tenant(monkeypatch):
    captured = {}

    def provision(**kwargs):
        captured.update(kwargs)
        return {"subject_id": str(kwargs["target_subject_id"]), "status": "active"}

    monkeypatch.setattr(tenant_admin.membership_store, "provision_member", provision)
    response = _client().post(
        "/api/tenant/members",
        json={"external_subject": "new-user", "role": "member"},
    )
    assert response.status_code == 201
    assert captured["tenant_id"] == TENANT_ID
    assert captured["actor_subject_id"] == ACTOR_ID
    assert captured["target_subject_id"] == derive_subject_id(
        "https://securetoken.google.com/test-project", "new-user"
    )


def test_non_admin_cannot_manage_members(monkeypatch):
    monkeypatch.setattr(
        tenant_admin.membership_store,
        "list_members",
        lambda **_kwargs: [{"unexpected": True}],
    )
    assert _client("member").get("/api/tenant/members").status_code == 403


def test_revocation_requires_explicit_confirmation(monkeypatch):
    called = False

    def revoke(**_kwargs):
        nonlocal called
        called = True
        return {"status": "revoked"}

    monkeypatch.setattr(tenant_admin.membership_store, "revoke_member", revoke)
    client = _client()
    assert client.delete(f"/api/tenant/members/{TARGET_ID}").status_code == 409
    assert called is False
    response = client.delete(
        f"/api/tenant/members/{TARGET_ID}", params={"confirm": "true"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"


def test_policy_conflict_is_safe(monkeypatch):
    def conflict(**_kwargs):
        raise tenant_admin.MembershipConflictError("sensitive database detail")

    monkeypatch.setattr(tenant_admin.membership_store, "update_role", conflict)
    response = _client().patch(
        f"/api/tenant/members/{TARGET_ID}", json={"role": "admin"}
    )
    assert response.status_code == 409
    assert "sensitive" not in response.text
