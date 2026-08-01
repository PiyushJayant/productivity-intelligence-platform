"""Authoritative tenant-membership access through private MCP Toolbox tools."""

from __future__ import annotations

import atexit
import json
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from toolbox_core import ToolboxSyncClient

from productivity_intelligence.config import settings
from productivity_intelligence.google_auth_headers import RefreshingGoogleAuthHeaders

VALID_ROLES = {"owner", "admin", "member", "viewer"}


class MembershipDeniedError(PermissionError):
    """The authenticated subject has no active membership."""


class MembershipUnavailableError(RuntimeError):
    """The authoritative membership service could not be reached."""


class MembershipConflictError(RuntimeError):
    """A requested membership transition violates an invariant."""


@dataclass(frozen=True)
class Membership:
    tenant_id: uuid.UUID
    subject_id: uuid.UUID
    external_subject: str
    role: str
    status: str = "active"


def _decode_rows(value: str) -> list[dict[str, Any]]:
    decoded = json.loads(value)
    if decoded is None:
        return []
    if isinstance(decoded, list):
        return decoded
    if isinstance(decoded, dict):
        for key in ("rows", "result", "data"):
            if isinstance(decoded.get(key), list):
                return decoded[key]
        return [decoded]
    raise MembershipUnavailableError("membership response has an invalid shape")


class ToolboxMembershipStore:
    """Use fixed SQL tools; no caller-authored SQL reaches AlloyDB."""

    def __init__(self) -> None:
        self._headers = RefreshingGoogleAuthHeaders(audience=settings.toolbox_audience)
        self._client: ToolboxSyncClient | None = None
        self._tools: dict[str, Any] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            client, self._client = self._client, None
            self._tools.clear()
        if client is not None:
            client.close()

    def _tool(self, name: str):
        with self._lock:
            if self._client is None:
                self._client = ToolboxSyncClient(
                    settings.toolbox_url,
                    client_headers={"Authorization": self._headers.authorization},
                )
            if name not in self._tools:
                self._tools[name] = self._client.load_tool(name)
            return self._tools[name]

    def _invoke(
        self, name: str, *, policy_operation: bool = False, **parameters: object
    ) -> list[dict[str, Any]]:
        try:
            return _decode_rows(self._tool(name)(**parameters))
        except MembershipDeniedError:
            raise
        except Exception as error:
            message = str(error).lower()
            if policy_operation and any(
                marker in message
                for marker in (
                    "42501",
                    "23514",
                    "22023",
                    "not authorized",
                    "last tenant owner",
                    "unsupported tenant role",
                )
            ):
                raise MembershipConflictError(
                    "membership transition violates tenant policy"
                ) from error
            raise MembershipUnavailableError(
                "tenant membership verification is temporarily unavailable"
            ) from error

    def authorize(
        self,
        *,
        tenant_id: uuid.UUID,
        subject_id: uuid.UUID,
        issuer: str,
        external_subject: str,
    ) -> str:
        rows = self._invoke(
            "authorize_identity",
            tenant_id=str(tenant_id),
            subject_id=str(subject_id),
            issuer=issuer,
            external_subject=external_subject,
        )
        if len(rows) != 1 or rows[0].get("role") not in VALID_ROLES:
            raise MembershipDeniedError("no active tenant membership")
        return str(rows[0]["role"])

    def list_members(self, tenant_id: uuid.UUID, actor_subject_id: uuid.UUID):
        return self._invoke(
            "list_tenant_members",
            policy_operation=True,
            tenant_id=str(tenant_id),
            actor_subject_id=str(actor_subject_id),
        )

    def provision_member(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_subject_id: uuid.UUID,
        target_subject_id: uuid.UUID,
        issuer: str,
        external_subject: str,
        role: str,
    ) -> dict[str, Any]:
        if role not in VALID_ROLES:
            raise ValueError("unsupported tenant role")
        rows = self._invoke(
            "provision_tenant_member",
            policy_operation=True,
            tenant_id=str(tenant_id),
            actor_subject_id=str(actor_subject_id),
            target_subject_id=str(target_subject_id),
            issuer=issuer,
            external_subject=external_subject,
            role=role,
        )
        if len(rows) != 1:
            raise MembershipConflictError("membership was not provisioned")
        return rows[0]

    def update_role(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_subject_id: uuid.UUID,
        target_subject_id: uuid.UUID,
        role: str,
    ) -> dict[str, Any]:
        if role not in VALID_ROLES:
            raise ValueError("unsupported tenant role")
        rows = self._invoke(
            "update_tenant_member_role",
            policy_operation=True,
            tenant_id=str(tenant_id),
            actor_subject_id=str(actor_subject_id),
            target_subject_id=str(target_subject_id),
            role=role,
        )
        if len(rows) != 1:
            raise MembershipConflictError("membership role was not updated")
        return rows[0]

    def revoke_member(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_subject_id: uuid.UUID,
        target_subject_id: uuid.UUID,
    ) -> dict[str, Any]:
        rows = self._invoke(
            "revoke_tenant_member",
            policy_operation=True,
            tenant_id=str(tenant_id),
            actor_subject_id=str(actor_subject_id),
            target_subject_id=str(target_subject_id),
        )
        if len(rows) != 1:
            raise MembershipConflictError("membership was not revoked")
        return rows[0]


membership_store = ToolboxMembershipStore()
atexit.register(membership_store.close)
