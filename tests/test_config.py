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
    ):
        monkeypatch.delenv(name, raising=False)
    values = {
        "APP_MODE": "full",
        "MODEL": "gemini-2.5-flash",
        "DEFAULT_TIMEZONE": "Asia/Kolkata",
        "LOG_LEVEL": "INFO",
        "REQUEST_ID_HEADER": "X-Request-ID",
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
    monkeypatch.delenv("MODEL", raising=False)
    with pytest.raises(ValueError, match="MODEL is required"):
        importlib.reload(config)


def test_invalid_generation_budget_is_rejected(monkeypatch):
    with pytest.raises(ValueError, match="ROUTER_MAX_OUTPUT_TOKENS"):
        reload_config(monkeypatch, ROUTER_MAX_OUTPUT_TOKENS="-1")


def test_invalid_timezone_and_observability_values_are_rejected(monkeypatch):
    with pytest.raises(ValueError, match="DEFAULT_TIMEZONE"):
        reload_config(monkeypatch, DEFAULT_TIMEZONE="not-a-timezone")
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        reload_config(monkeypatch, LOG_LEVEL="verbose")
    with pytest.raises(ValueError, match="REQUEST_ID_HEADER"):
        reload_config(monkeypatch, REQUEST_ID_HEADER="bad header")
