"""Tests for production startup settings validation."""

import pytest

from app.main import validate_startup_settings


def test_validate_startup_settings_skips_non_production(monkeypatch):
    monkeypatch.setattr("app.main.settings.ENVIRONMENT", "development")
    monkeypatch.setattr("app.main.settings.SECRET_KEY", "change-me-in-production")
    monkeypatch.setattr("app.main.settings.OPENAI_API_KEY", "")
    validate_startup_settings()  # should not raise


def test_validate_startup_settings_rejects_weak_secret(monkeypatch):
    monkeypatch.setattr("app.main.settings.ENVIRONMENT", "production")
    monkeypatch.setattr("app.main.settings.SECRET_KEY", "change-me-in-production")
    monkeypatch.setattr("app.main.settings.OPENAI_API_KEY", "sk-test")

    with pytest.raises(RuntimeError, match="Invalid SECRET_KEY"):
        validate_startup_settings()


def test_validate_startup_settings_requires_openai_key(monkeypatch):
    monkeypatch.setattr("app.main.settings.ENVIRONMENT", "production")
    monkeypatch.setattr("app.main.settings.SECRET_KEY", "a" * 40)
    monkeypatch.setattr("app.main.settings.OPENAI_API_KEY", "")

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        validate_startup_settings()
