from __future__ import annotations

import importlib

import pytest

import productivity_assistant.config as config


def reload_config(monkeypatch, **values):
    for name in ("APP_MODE", "PROTOTYPE_MODE", "MODEL"):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return importlib.reload(config)


def test_defaults_to_full_mode(monkeypatch):
    module = reload_config(monkeypatch)
    assert module.settings.app_mode == "full"
    assert module.settings.model == "gemini-2.5-flash"


def test_legacy_prototype_mode(monkeypatch):
    module = reload_config(monkeypatch, PROTOTYPE_MODE="true")
    assert module.settings.app_mode == "prototype"


def test_app_mode_takes_precedence(monkeypatch):
    module = reload_config(
        monkeypatch, APP_MODE="full", PROTOTYPE_MODE="true", MODEL="custom-model"
    )
    assert module.settings.app_mode == "full"
    assert module.settings.model == "custom-model"


def test_invalid_mode_is_rejected(monkeypatch):
    with pytest.raises(ValueError, match="APP_MODE"):
        reload_config(monkeypatch, APP_MODE="degraded")
