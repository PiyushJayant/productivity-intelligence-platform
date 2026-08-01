"""Private privacy-request operations backed by fixed Toolbox SQL tools."""

from __future__ import annotations

import atexit
import json
import threading
import uuid
from typing import Any

from toolbox_core import ToolboxSyncClient

from productivity_intelligence.config import settings
from productivity_intelligence.google_auth_headers import RefreshingGoogleAuthHeaders


class PrivacyConflictError(RuntimeError):
    """A privacy request violates an authorization or lifecycle invariant."""


class PrivacyUnavailableError(RuntimeError):
    """The private persistence capability is temporarily unavailable."""


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
    raise PrivacyUnavailableError("privacy response has an invalid shape")


class ToolboxPrivacyStore:
    """Invoke non-model-visible privacy tools with server-derived identities."""

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

    def _invoke(self, name: str, **parameters: object) -> list[dict[str, Any]]:
        try:
            return _decode_rows(self._tool(name)(**parameters))
        except Exception as error:
            message = str(error).lower()
            if any(
                marker in message
                for marker in (
                    "42501",
                    "23514",
                    "not authorized",
                    "last tenant owner",
                )
            ):
                raise PrivacyConflictError("privacy request violates tenant policy") from error
            raise PrivacyUnavailableError(
                "privacy request persistence is temporarily unavailable"
            ) from error

    def request_erasure(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_subject_id: uuid.UUID,
        target_subject_id: uuid.UUID,
    ) -> dict[str, Any]:
        rows = self._invoke(
            "request_subject_erasure",
            tenant_id=str(tenant_id),
            actor_subject_id=str(actor_subject_id),
            target_subject_id=str(target_subject_id),
        )
        if len(rows) != 1:
            raise PrivacyConflictError("privacy request was not created")
        return rows[0]

    def list_erasure_requests(
        self, *, tenant_id: uuid.UUID, actor_subject_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        return self._invoke(
            "list_subject_erasure_requests",
            tenant_id=str(tenant_id),
            actor_subject_id=str(actor_subject_id),
        )


privacy_store = ToolboxPrivacyStore()
atexit.register(privacy_store.close)
