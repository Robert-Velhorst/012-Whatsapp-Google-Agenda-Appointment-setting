from __future__ import annotations

import pytest

from scheduler.config import Settings, validate_server_bind


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_development_server_allows_loopback(host):
    validate_server_bind("development", host)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "::", "example.invalid"])
def test_development_server_rejects_non_loopback(host):
    with pytest.raises(RuntimeError, match="must bind to loopback"):
        validate_server_bind("development", host)


def test_test_server_rejects_non_loopback():
    with pytest.raises(RuntimeError, match="must bind to loopback"):
        validate_server_bind("test", "0.0.0.0")


def test_production_may_bind_non_loopback():
    validate_server_bind("production", "0.0.0.0")


def test_development_auth_defaults_are_random_per_settings_instance(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)

    first = Settings.from_env()
    second = Settings.from_env()

    assert len(first.flask_secret_key) >= 32
    assert len(first.admin_api_token) >= 32
    assert first.flask_secret_key != "development-only-change-me"
    assert first.admin_api_token != "development-admin-token"
    assert first.flask_secret_key != second.flask_secret_key
    assert first.admin_api_token != second.admin_api_token


def test_production_does_not_fill_missing_auth_secrets(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)

    settings = Settings.from_env()

    assert settings.flask_secret_key == ""
    assert settings.admin_api_token == ""
    errors, _ = settings.validation()
    assert any("FLASK_SECRET_KEY" in error for error in errors)
    assert any("ADMIN_API_TOKEN" in error for error in errors)
