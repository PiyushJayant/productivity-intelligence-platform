from __future__ import annotations

import importlib

import pytest

import productivity_intelligence.config as config


def reload_config(monkeypatch, **values):
    for name in (
        "APP_MODE",
        "MODEL",
        "DEFAULT_TIMEZONE",
        "LOG_LEVEL",
        "REQUEST_ID_HEADER",
        "BIGQUERY_ANALYTICS_PROCEDURE",
        "ANALYTICS_MAX_RANGE_DAYS",
        "ANALYTICS_QUERY_TIMEOUT_SECONDS",
        "AUTH_MODE",
        "IDENTITY_PLATFORM_PROJECT_ID",
        "DEFAULT_TENANT_ID",
        "DEMO_SUBJECT_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    values = {
        "APP_MODE": "full",
        "MODEL": "gemini-2.5-flash",
        "DEFAULT_TIMEZONE": "Asia/Kolkata",
        "LOG_LEVEL": "INFO",
        "REQUEST_ID_HEADER": "X-Request-ID",
        "BIGQUERY_ANALYTICS_PROCEDURE": "get_productivity_trends_v2",
        "ANALYTICS_MAX_RANGE_DAYS": "730",
        "ANALYTICS_QUERY_TIMEOUT_SECONDS": "30",
        "AUTH_MODE": "disabled",
        "IDENTITY_PLATFORM_PROJECT_ID": "test-project",
        "DEFAULT_TENANT_ID": "11111111-1111-4111-8111-111111111111",
        "DEMO_SUBJECT_ID": "22222222-2222-4222-8222-222222222222",
        **values,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return importlib.reload(config)


def test_configured_full_mode(monkeypatch):
    module = reload_config(monkeypatch)
    assert module.settings.app_mode == "full"
    assert module.settings.model == "gemini-2.5-flash"


def test_explicit_mode_and_model(monkeypatch):
    module = reload_config(monkeypatch, APP_MODE="prototype", MODEL="custom-model")
    assert module.settings.app_mode == "prototype"
    module = reload_config(monkeypatch, APP_MODE="full", MODEL="custom-model")
    assert module.settings.app_mode == "full"
    assert module.settings.model == "custom-model"


def test_invalid_mode_is_rejected(monkeypatch):
    with pytest.raises(ValueError, match="APP_MODE"):
        reload_config(monkeypatch, APP_MODE="degraded")


def test_missing_required_model_is_rejected(monkeypatch):
    # An explicit empty value prevents the real local .env from filling the key
    # during reload, so this remains isolated after deployment initialization.
    monkeypatch.setenv("MODEL", "")
    with pytest.raises(ValueError, match="MODEL is required"):
        importlib.reload(config)


def test_invalid_generation_budget_is_rejected(monkeypatch):
    with pytest.raises(ValueError, match="ROUTER_MAX_OUTPUT_TOKENS"):
        reload_config(monkeypatch, ROUTER_MAX_OUTPUT_TOKENS="-1")


def test_context_window_must_be_positive(monkeypatch):
    with pytest.raises(ValueError, match="AGENT_CONTEXT_MAX_EVENTS"):
        reload_config(monkeypatch, AGENT_CONTEXT_MAX_EVENTS="0")


def test_analytics_limits_and_routine_name_are_validated(monkeypatch):
    with pytest.raises(ValueError, match="ANALYTICS_MAX_RANGE_DAYS"):
        reload_config(monkeypatch, ANALYTICS_MAX_RANGE_DAYS="0")
    with pytest.raises(ValueError, match="ANALYTICS_QUERY_TIMEOUT_SECONDS"):
        reload_config(monkeypatch, ANALYTICS_QUERY_TIMEOUT_SECONDS="0")
    with pytest.raises(ValueError, match="BIGQUERY_ANALYTICS_PROCEDURE"):
        reload_config(
            monkeypatch,
            BIGQUERY_ANALYTICS_PROCEDURE="unsafe-procedure;drop",
        )


def test_invalid_timezone_and_observability_values_are_rejected(monkeypatch):
    with pytest.raises(ValueError, match="DEFAULT_TIMEZONE"):
        reload_config(monkeypatch, DEFAULT_TIMEZONE="not-a-timezone")
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        reload_config(monkeypatch, LOG_LEVEL="verbose")
    with pytest.raises(ValueError, match="REQUEST_ID_HEADER"):
        reload_config(monkeypatch, REQUEST_ID_HEADER="bad header")


def test_identity_configuration_fails_closed(monkeypatch):
    with pytest.raises(ValueError, match="AUTH_MODE"):
        reload_config(monkeypatch, AUTH_MODE="optional")
    with pytest.raises(ValueError, match="IDENTITY_PLATFORM_PROJECT_ID"):
        reload_config(
            monkeypatch,
            AUTH_MODE="identity_platform",
            IDENTITY_PLATFORM_PROJECT_ID="",
        )
    with pytest.raises(ValueError, match="DEFAULT_TENANT_ID"):
        reload_config(monkeypatch, DEFAULT_TENANT_ID="not-a-uuid")
