"""Shared MCP tool helpers for the productivity assistant.

Uses the same patterns taught in the codelabs:
- MCP Toolbox for Databases (ToolboxSyncClient) → AlloyDB
- Google-hosted BigQuery MCP server (MCPToolset + StreamableHTTPConnectionParams) → BigQuery
"""
import atexit
import base64
import json
import logging
import threading
import time
from collections.abc import Mapping

import google.auth
import google.auth.transport.requests
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
from google.oauth2 import id_token
from toolbox_core import ToolboxSyncClient

from productivity_assistant.config import settings

LOGGER = logging.getLogger(__name__)
BIGQUERY_READ_ONLY_TOOLS = [
    "execute_sql_readonly",
    "list_dataset_ids",
    "get_dataset_info",
    "list_table_ids",
    "get_table_info",
]


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


_toolbox_headers = (
    RefreshingGoogleAuthHeaders(audience=settings.toolbox_audience)
    if settings.toolbox_audience
    else None
)
_bigquery_headers: RefreshingGoogleAuthHeaders | None = None
_toolbox_clients: list[ToolboxSyncClient] = []
_toolbox_clients_lock = threading.Lock()


def close_toolbox_clients() -> None:
    """Close long-lived Toolbox transports during orderly process shutdown."""
    with _toolbox_clients_lock:
        clients = list(_toolbox_clients)
        _toolbox_clients.clear()
    for client in clients:
        try:
            client.close()
        except Exception:  # pragma: no cover - best-effort shutdown
            LOGGER.exception("Failed to close a Toolbox client cleanly")


atexit.register(close_toolbox_clients)


def load_toolset(toolset_name: str):
    """Load a toolset from the configured MCP Toolbox server.

    Returns None when the toolbox is not reachable so Cloud Shell-only
    deployments can still start with the hosted BigQuery agent.
    """
    toolbox = None
    try:
        client_headers = None
        if _toolbox_headers is not None:
            client_headers = {"Authorization": _toolbox_headers.authorization}
        toolbox = ToolboxSyncClient(settings.toolbox_url, client_headers=client_headers)
        tools = toolbox.load_toolset(toolset_name)
        # Toolbox tools use their client's background event loop and HTTP session
        # at invocation time. Keep the owning client alive for the process lifetime.
        with _toolbox_clients_lock:
            _toolbox_clients.append(toolbox)
        toolbox = None
        return tools
    except Exception as exc:  # pragma: no cover - startup resilience
        LOGGER.warning(
            "Skipping toolset %s because MCP Toolbox is unavailable at %s: %s",
            toolset_name,
            settings.toolbox_url,
            exc,
        )
        return None
    finally:
        if toolbox is not None:
            toolbox.close()


def get_bigquery_mcp_toolset() -> MCPToolset:
    """Build a toolset for the Google-hosted BigQuery MCP server.

    Uses Application Default Credentials (ADC) with BigQuery scope and
    passes an OAuth Bearer token — the same pattern as the bakery / location
    intelligence codelab.
    """
    global _bigquery_headers
    if _bigquery_headers is None:
        _bigquery_headers = RefreshingGoogleAuthHeaders(
            scopes=["https://www.googleapis.com/auth/bigquery"]
        )

    return MCPToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=settings.bigquery_mcp_url,
            timeout=30.0,
            sse_read_timeout=300.0,
        ),
        header_provider=_bigquery_headers.as_bigquery_headers,
        tool_filter=BIGQUERY_READ_ONLY_TOOLS,
    )
