"""Validated runtime configuration for Productivity Intelligence Platform."""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

VALID_APP_MODES = {"full", "prototype"}
VALID_AUTH_MODES = {"disabled", "identity_platform"}
VALID_ANALYTICS_BACKENDS = {"federated", "native"}

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


def _sql_identifier(name: str) -> str:
    value = _required(name)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"{name} must be a valid SQL identifier")
    return value


def _optional(name: str) -> str:
    return os.getenv(name, "").strip()


def _uuid(name: str) -> uuid.UUID:
    value = _required(name)
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a UUID") from error


def _secret(name: str, minimum_length: int = 32) -> str:
    value = _required(name)
    if value.startswith(("change-me", "replace-", "your-")):
        if os.getenv("ENVIRONMENT", "").lower() == "production":
            raise ValueError(f"{name} is still a placeholder")
    elif len(value) < minimum_length:
        raise ValueError(f"{name} must be at least {minimum_length} characters")
    return value


@dataclass(frozen=True)
class Settings:
    app_mode: str
    model: str
    embedding_model: str
    google_cloud_project: str
    region: str
    toolbox_url: str
    toolbox_audience: str
    bigquery_mcp_url: str
    bigquery_dataset: str
    bigquery_analytics_procedure: str
    router_max_output_tokens: int
    router_thinking_budget: int
    specialist_max_output_tokens: int
    specialist_thinking_budget: int
    analytics_max_output_tokens: int
    analytics_thinking_budget: int
    analytics_max_range_days: int
    analytics_query_timeout_seconds: int
    agent_context_max_events: int
    model_temperature: float
    default_timezone: str
    default_page_size: int
    log_level: str
    structured_logging: bool
    enable_request_logging: bool
    request_id_header: str
    auth_mode: str
    identity_platform_project_id: str
    identity_platform_tenant_id: str
    identity_tenant_claim: str
    identity_role_claim: str
    default_tenant_id: uuid.UUID
    demo_subject_id: uuid.UUID
    auth_clock_skew_seconds: int
    analytics_backend: str
    bigquery_native_tvf: str
    analytics_retry_attempts: int
    analytics_retry_base_seconds: float
    analytics_retry_max_seconds: float
    pseudonymization_key: str
    privacy_retention_days: int
    taxonomy_version: str

    @classmethod
    def from_env(cls) -> "Settings":
        app_mode = _required("APP_MODE").lower()
        if app_mode not in VALID_APP_MODES:
            raise ValueError(
                f"APP_MODE must be one of {sorted(VALID_APP_MODES)}, got {app_mode!r}"
            )

        model = _required("MODEL")
        auth_mode = _required("AUTH_MODE").lower()
        if auth_mode not in VALID_AUTH_MODES:
            raise ValueError(
                f"AUTH_MODE must be one of {sorted(VALID_AUTH_MODES)}, "
                f"got {auth_mode!r}"
            )
        identity_project = _optional("IDENTITY_PLATFORM_PROJECT_ID")
        if auth_mode == "identity_platform" and not identity_project:
            raise ValueError(
                "IDENTITY_PLATFORM_PROJECT_ID is required when AUTH_MODE is "
                "identity_platform"
            )
        if auth_mode == "disabled" and _optional("ENVIRONMENT").lower() == "production":
            raise ValueError("AUTH_MODE=disabled is forbidden in production")
        analytics_backend = _required("ANALYTICS_BACKEND").lower()
        if analytics_backend not in VALID_ANALYTICS_BACKENDS:
            raise ValueError(
                "ANALYTICS_BACKEND must be federated or native"
            )

        return cls(
            app_mode=app_mode,
            model=model,
            embedding_model=_required("EMBEDDING_MODEL"),
            google_cloud_project=_required("GOOGLE_CLOUD_PROJECT"),
            region=_required("REGION"),
            toolbox_url=_required("TOOLBOX_URL").rstrip("/"),
            toolbox_audience=_required("TOOLBOX_AUDIENCE").rstrip("/"),
            bigquery_mcp_url=_required("BIGQUERY_MCP_URL"),
            bigquery_dataset=_sql_identifier("BIGQUERY_DATASET"),
            bigquery_analytics_procedure=_sql_identifier(
                "BIGQUERY_ANALYTICS_PROCEDURE"
            ),
            router_max_output_tokens=_integer("ROUTER_MAX_OUTPUT_TOKENS"),
            router_thinking_budget=_integer("ROUTER_THINKING_BUDGET"),
            specialist_max_output_tokens=_integer("SPECIALIST_MAX_OUTPUT_TOKENS"),
            specialist_thinking_budget=_integer("SPECIALIST_THINKING_BUDGET"),
            analytics_max_output_tokens=_integer("ANALYTICS_MAX_OUTPUT_TOKENS"),
            analytics_thinking_budget=_integer("ANALYTICS_THINKING_BUDGET"),
            analytics_max_range_days=_positive_integer(
                "ANALYTICS_MAX_RANGE_DAYS"
            ),
            analytics_query_timeout_seconds=_positive_integer(
                "ANALYTICS_QUERY_TIMEOUT_SECONDS"
            ),
            agent_context_max_events=_positive_integer("AGENT_CONTEXT_MAX_EVENTS"),
            model_temperature=_float("MODEL_TEMPERATURE"),
            default_timezone=_timezone("DEFAULT_TIMEZONE"),
            default_page_size=_positive_integer("DEFAULT_PAGE_SIZE"),
            log_level=_log_level("LOG_LEVEL"),
            structured_logging=_boolean("STRUCTURED_LOGGING"),
            enable_request_logging=_boolean("ENABLE_REQUEST_LOGGING"),
            request_id_header=_header_name("REQUEST_ID_HEADER"),
            auth_mode=auth_mode,
            identity_platform_project_id=identity_project,
            identity_platform_tenant_id=_optional("IDENTITY_PLATFORM_TENANT_ID"),
            identity_tenant_claim=_required("IDENTITY_TENANT_CLAIM"),
            identity_role_claim=_required("IDENTITY_ROLE_CLAIM"),
            default_tenant_id=_uuid("DEFAULT_TENANT_ID"),
            demo_subject_id=_uuid("DEMO_SUBJECT_ID"),
            auth_clock_skew_seconds=_integer("AUTH_CLOCK_SKEW_SECONDS"),
            analytics_backend=analytics_backend,
            bigquery_native_tvf=_sql_identifier("BIGQUERY_NATIVE_TVF"),
            analytics_retry_attempts=_positive_integer(
                "ANALYTICS_RETRY_ATTEMPTS"
            ),
            analytics_retry_base_seconds=_float(
                "ANALYTICS_RETRY_BASE_SECONDS"
            ),
            analytics_retry_max_seconds=_float(
                "ANALYTICS_RETRY_MAX_SECONDS"
            ),
            pseudonymization_key=_secret("PSEUDONYMIZATION_KEY"),
            privacy_retention_days=_positive_integer("PRIVACY_RETENTION_DAYS"),
            taxonomy_version=_sql_identifier("TAXONOMY_VERSION"),
        )


settings = Settings.from_env()
