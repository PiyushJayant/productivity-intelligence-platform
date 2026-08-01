"""Shared MCP tool helpers for Productivity Intelligence Platform.

Uses refreshable Google credentials for authenticated service integrations:
- MCP Toolbox for Databases (ToolboxSyncClient) → AlloyDB
- Google-hosted BigQuery MCP server (`McpToolset` + streamable HTTP) → BigQuery
"""
import atexit
import logging
import threading

from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from toolbox_core import ToolboxSyncClient

from productivity_intelligence.config import settings
from productivity_intelligence.google_auth_headers import RefreshingGoogleAuthHeaders
from productivity_intelligence.identity import (
    current_subject_id,
    current_tenant_id,
)

LOGGER = logging.getLogger(__name__)
BIGQUERY_READ_ONLY_TOOLS = [
    "execute_sql_readonly",
    "list_dataset_ids",
    "get_dataset_info",
    "list_table_ids",
    "get_table_info",
]


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
        # Bound parameters are evaluated at invocation time and removed from the
        # model-visible tool schema by Toolbox. The LLM cannot select or alter
        # tenant and subject identifiers.
        tools = toolbox.load_toolset(
            toolset_name,
            bound_params={
                "tenant_id": current_tenant_id,
                "subject_id": current_subject_id,
            },
            strict=True,
        )
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


def get_bigquery_mcp_toolset() -> McpToolset:
    """Build a toolset for the Google-hosted BigQuery MCP server.

    Uses Application Default Credentials (ADC) with BigQuery scope and passes a
    refreshable OAuth Bearer token to the hosted BigQuery MCP service.
    """
    global _bigquery_headers
    if _bigquery_headers is None:
        _bigquery_headers = RefreshingGoogleAuthHeaders(
            scopes=["https://www.googleapis.com/auth/bigquery"]
        )

    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=settings.bigquery_mcp_url,
            timeout=30.0,
            sse_read_timeout=300.0,
        ),
        header_provider=_bigquery_headers.as_bigquery_headers,
        tool_filter=BIGQUERY_READ_ONLY_TOOLS,
    )
