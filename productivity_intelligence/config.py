"""Validated runtime configuration for Productivity Intelligence Platform."""

from __future__ import annotations

import os
from dataclasses import dataclass

VALID_APP_MODES = {"full", "prototype"}

@dataclass(frozen=True)
class Settings:
    app_mode: str
    model: str
    google_cloud_project: str
    toolbox_url: str
    toolbox_audience: str
    bigquery_mcp_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        app_mode = os.getenv("APP_MODE", "full").strip().lower()
        if app_mode not in VALID_APP_MODES:
            raise ValueError(
                f"APP_MODE must be one of {sorted(VALID_APP_MODES)}, got {app_mode!r}"
            )

        model = os.getenv("MODEL", "gemini-2.5-flash").strip()
        if not model:
            raise ValueError("MODEL must not be empty")

        return cls(
            app_mode=app_mode,
            model=model,
            google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT", "").strip(),
            toolbox_url=os.getenv("TOOLBOX_URL", "http://127.0.0.1:5000").rstrip("/"),
            toolbox_audience=os.getenv("TOOLBOX_AUDIENCE", "").rstrip("/"),
            bigquery_mcp_url=os.getenv(
                "BIGQUERY_MCP_URL", "https://bigquery.googleapis.com/mcp"
            ).strip(),
        )


settings = Settings.from_env()
