from __future__ import annotations

from datetime import datetime, timedelta, timezone

import productivity_intelligence.tools as tools_module
from productivity_intelligence.tools import RefreshingGoogleAuthHeaders


class FakeCredentials:
    def __init__(self):
        self.token = ""
        self.expiry = None
        self.refreshes = 0

    def refresh(self, _request):
        self.refreshes += 1
        self.token = f"access-{self.refreshes}"
        self.expiry = datetime.now(timezone.utc) + timedelta(minutes=30)


def test_access_token_is_cached_until_expiry():
    headers = RefreshingGoogleAuthHeaders.__new__(RefreshingGoogleAuthHeaders)
    headers._audience = None
    headers._request = object()
    headers._lock = __import__("threading").Lock()
    headers._token = ""
    headers._expires_at = 0.0
    headers._credentials = FakeCredentials()
    headers._project_id = "test-project"

    first = headers.as_bigquery_headers()
    second = headers.as_bigquery_headers()

    assert first == {
        "Authorization": "Bearer access-1",
        "x-goog-user-project": "test-project",
    }
    assert second == first
    assert headers._credentials.refreshes == 1


def test_id_token_refreshes_when_near_expiry(monkeypatch):
    headers = RefreshingGoogleAuthHeaders.__new__(RefreshingGoogleAuthHeaders)
    headers._audience = "https://toolbox.example"
    headers._request = object()
    headers._lock = __import__("threading").Lock()
    headers._token = "old"
    headers._expires_at = 0.0
    headers._credentials = None
    headers._project_id = ""
    monkeypatch.setattr(headers, "_refresh_id_token", lambda: setattr(headers, "_token", "new"))
    monkeypatch.setattr(headers, "_expires_at", 0.0)

    assert headers.authorization() == "Bearer new"


def test_loaded_toolset_keeps_owning_client_open(monkeypatch):
    class FakeToolboxClient:
        instances = []

        def __init__(self, *_args, **_kwargs):
            self.closed = False
            self.instances.append(self)

        def load_toolset(self, name):
            return [f"tool-from-{name}"]

        def close(self):
            self.closed = True

    tools_module.close_toolbox_clients()
    monkeypatch.setattr(tools_module, "ToolboxSyncClient", FakeToolboxClient)
    monkeypatch.setattr(tools_module, "_toolbox_headers", None)

    assert tools_module.load_toolset("notes-tools") == ["tool-from-notes-tools"]
    client = FakeToolboxClient.instances[0]
    assert client.closed is False

    tools_module.close_toolbox_clients()
    assert client.closed is True
