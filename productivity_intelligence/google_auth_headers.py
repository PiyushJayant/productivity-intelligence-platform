"""Refreshable Google authorization headers for private service calls."""

from __future__ import annotations

import base64
import json
import threading
import time
from collections.abc import Mapping

import google.auth
import google.auth.transport.requests
from google.oauth2 import id_token

from productivity_intelligence.config import settings


class RefreshingGoogleAuthHeaders:
    """Callable headers backed by refreshable Google application credentials."""

    def __init__(self, *, audience: str | None = None, scopes: list[str] | None = None):
        self._audience = audience
        self._request = google.auth.transport.requests.Request()
        self._lock = threading.Lock()
        self._token = ""
        self._expires_at = 0.0
        self._credentials = None
        self._project_id = settings.google_cloud_project
        if scopes:
            self._credentials, detected_project = google.auth.default(scopes=scopes)
            self._project_id = self._project_id or detected_project or ""

    @staticmethod
    def _jwt_expiry(token: str) -> float:
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return time.time() + 300

    def _refresh_id_token(self) -> None:
        self._token = id_token.fetch_id_token(self._request, self._audience)
        self._expires_at = self._jwt_expiry(self._token)

    def _refresh_access_token(self) -> None:
        if self._credentials is None:
            raise RuntimeError("OAuth credentials were not initialized")
        self._credentials.refresh(self._request)
        self._token = self._credentials.token
        expiry = getattr(self._credentials, "expiry", None)
        self._expires_at = expiry.timestamp() if expiry else time.time() + 300

    def token(self) -> str:
        with self._lock:
            if not self._token or self._expires_at <= time.time() + 60:
                if self._audience:
                    self._refresh_id_token()
                else:
                    self._refresh_access_token()
            return self._token

    def authorization(self) -> str:
        return f"Bearer {self.token()}"

    def as_bigquery_headers(self, _context=None) -> Mapping[str, str]:
        headers = {"Authorization": self.authorization()}
        if self._project_id:
            headers["x-goog-user-project"] = self._project_id
        return headers
