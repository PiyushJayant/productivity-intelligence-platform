"""Domain-separated pseudonymous identifiers for analytics boundaries."""

from __future__ import annotations

import hashlib
import hmac
import uuid


def tenant_token(key: str, tenant_id: uuid.UUID | str) -> str:
    payload = f"tenant:v1:{tenant_id}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def subject_token(
    key: str,
    tenant_id: uuid.UUID | str,
    subject_id: uuid.UUID | str,
) -> str:
    payload = f"subject:v1:{tenant_id}:{subject_id}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()
