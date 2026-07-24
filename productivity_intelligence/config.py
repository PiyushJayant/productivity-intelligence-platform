"""Validated runtime configuration for Productivity Intelligence Platform."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

VALID_APP_MODES = {"full", "prototype"}

load_dotenv(Path(__file__).parents[1] / ".env", override=False)


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _integer(name: str) -> int:
    raw = _required(name)
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _positive_integer(name: str) -> int:
    value = _integer(name)
    if value < 1:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _float(name: str) -> float:
    raw = _required(name)
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a number") from error
    if name == "MODEL_TEMPERATURE" and not 0 <= value <= 2:
        raise ValueError("MODEL_TEMPERATURE must be between 0 and 2")
    return value


def _boolean(name: str) -> bool:
    raw = _required(name).lower()
    if raw not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return raw == "true"


def _timezone(name: str) -> str:
    value = _required(name)
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"{name} must be a valid IANA timezone") from error
    return value


def _log_level(name: str) -> str:
    value = _required(name).upper()
    if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(f"{name} must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
    return value


def _header_name(name: str) -> str:
    value = _required(name)
    if not re.fullmatch(r"[A-Za-z0-9-]+", value):
        raise ValueError(f"{name} must be a valid HTTP header name")
    return value


@dataclass(frozen=True)
class Settings:
    app_mode: str
    model: str
    embedding_model: str
    google_cloud_project: str
    toolbox_url: str
    toolbox_audience: str
    bigquery_mcp_url: str
    bigquery_dataset: str
    router_max_output_tokens: int
    router_thinking_budget: int
    specialist_max_output_tokens: int
    specialist_thinking_budget: int
    analytics_max_output_tokens: int
    analytics_thinking_budget: int
    agent_context_max_events: int
    model_temperature: float
    default_timezone: str
    default_page_size: int
    log_level: str
    structured_logging: bool
    enable_request_logging: bool
    request_id_header: str

    @classmethod
    def from_env(cls) -> "Settings":
        app_mode = _required("APP_MODE").lower()
        if app_mode not in VALID_APP_MODES:
            raise ValueError(
                f"APP_MODE must be one of {sorted(VALID_APP_MODES)}, got {app_mode!r}"
            )

        model = _required("MODEL")

        return cls(
            app_mode=app_mode,
            model=model,
            embedding_model=_required("EMBEDDING_MODEL"),
            google_cloud_project=_required("GOOGLE_CLOUD_PROJECT"),
            toolbox_url=_required("TOOLBOX_URL").rstrip("/"),
            toolbox_audience=_required("TOOLBOX_AUDIENCE").rstrip("/"),
            bigquery_mcp_url=_required("BIGQUERY_MCP_URL"),
            bigquery_dataset=_required("BIGQUERY_DATASET"),
            router_max_output_tokens=_integer("ROUTER_MAX_OUTPUT_TOKENS"),
            router_thinking_budget=_integer("ROUTER_THINKING_BUDGET"),
            specialist_max_output_tokens=_integer("SPECIALIST_MAX_OUTPUT_TOKENS"),
            specialist_thinking_budget=_integer("SPECIALIST_THINKING_BUDGET"),
            analytics_max_output_tokens=_integer("ANALYTICS_MAX_OUTPUT_TOKENS"),
            analytics_thinking_budget=_integer("ANALYTICS_THINKING_BUDGET"),
            agent_context_max_events=_positive_integer("AGENT_CONTEXT_MAX_EVENTS"),
            model_temperature=_float("MODEL_TEMPERATURE"),
            default_timezone=_timezone("DEFAULT_TIMEZONE"),
            default_page_size=_positive_integer("DEFAULT_PAGE_SIZE"),
            log_level=_log_level("LOG_LEVEL"),
            structured_logging=_boolean("STRUCTURED_LOGGING"),
            enable_request_logging=_boolean("ENABLE_REQUEST_LOGGING"),
            request_id_header=_header_name("REQUEST_ID_HEADER"),
        )


settings = Settings.from_env()
