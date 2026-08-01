from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from productivity_intelligence import privacy_api
from productivity_intelligence.identity import RequestIdentity

TENANT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
ACTOR_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
TARGET_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


def _client(role: str = "member") -> TestClient:
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

    app.include_router(privacy_api.router)
    return TestClient(app)


def test_erasure_requires_exact_confirmation(monkeypatch):
    called = False

    def request_erasure(**_kwargs):
        nonlocal called
        called = True
        return {"status": "pending"}

    monkeypatch.setattr(privacy_api.privacy_store, "request_erasure", request_erasure)
    response = _client().post(
        "/api/privacy/erasure-requests", json={"confirmation": "yes"}
    )
    assert response.status_code == 409
    assert called is False


def test_self_erasure_uses_server_identity(monkeypatch):
    captured = {}

    def request_erasure(**kwargs):
        captured.update(kwargs)
        return {"id": "request-id", "status": "pending"}

    monkeypatch.setattr(privacy_api.privacy_store, "request_erasure", request_erasure)
    response = _client().post(
        "/api/privacy/erasure-requests",
        json={"confirmation": "ERASE_SUBJECT_DATA"},
    )
    assert response.status_code == 202
    assert captured == {
        "tenant_id": TENANT_ID,
        "actor_subject_id": ACTOR_ID,
        "target_subject_id": ACTOR_ID,
    }


def test_admin_target_is_passed_only_with_server_tenant(monkeypatch):
    captured = {}

    def request_erasure(**kwargs):
        captured.update(kwargs)
        return {"id": "request-id", "status": "pending"}

    monkeypatch.setattr(privacy_api.privacy_store, "request_erasure", request_erasure)
    response = _client("admin").post(
        "/api/privacy/erasure-requests",
        json={
            "subject_id": str(TARGET_ID),
            "confirmation": "ERASE_SUBJECT_DATA",
        },
    )
    assert response.status_code == 202
    assert captured["tenant_id"] == TENANT_ID
    assert captured["target_subject_id"] == TARGET_ID


def test_privacy_errors_do_not_expose_database_details(monkeypatch):
    def unavailable(**_kwargs):
        raise privacy_api.PrivacyUnavailableError("password=private")

    monkeypatch.setattr(privacy_api.privacy_store, "request_erasure", unavailable)
    response = _client().post(
        "/api/privacy/erasure-requests",
        json={"confirmation": "ERASE_SUBJECT_DATA"},
    )
    assert response.status_code == 503
    assert "password" not in response.text
