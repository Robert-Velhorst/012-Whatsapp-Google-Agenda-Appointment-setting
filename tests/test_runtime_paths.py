from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from scheduler import config
from scheduler import standalone


def test_frozen_runtime_root_is_executable_parent(monkeypatch, tmp_path):
    package = tmp_path / "AgendaRelay"
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config.sys, "executable", str(package / "AgendaRelay.exe"))

    assert config._runtime_root() == package


def test_frozen_runtime_resolves_relative_paths_beside_executable(monkeypatch, tmp_path):
    package = tmp_path / "AgendaRelay"
    package.mkdir()
    monkeypatch.setattr(config, "APP_ROOT", package)
    monkeypatch.setenv("DATABASE_PATH", "data/scheduler.sqlite3")
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", "data/google-token.json")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", "credentials/client-secret.json")

    settings = config.Settings.from_env()

    assert settings.database_path == package / "data" / "scheduler.sqlite3"
    assert settings.google_token_file == str(package / "data" / "google-token.json")
    assert settings.google_client_secrets_file == str(package / "credentials" / "client-secret.json")


def test_absolute_provider_paths_remain_absolute(monkeypatch, tmp_path):
    package = tmp_path / "AgendaRelay"
    database = tmp_path / "external" / "scheduler.sqlite3"
    token = tmp_path / "external" / "google-token.json"
    client_secrets = tmp_path / "external" / "client-secret.json"
    monkeypatch.setattr(config, "APP_ROOT", package)

    settings = config.Settings.from_env({
        "database_path": database,
        "google_token_file": str(token),
        "google_client_secrets_file": str(client_secrets),
    })

    assert settings.database_path == database
    assert settings.google_token_file == str(token)
    assert settings.google_client_secrets_file == str(client_secrets)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("max_inbound_per_contact_per_hour", 0, "MAX_INBOUND_PER_CONTACT_PER_HOUR"),
        ("max_inbound_total_per_hour", 100_001, "MAX_INBOUND_TOTAL_PER_HOUR"),
        ("max_inbound_messages_per_webhook", 201, "MAX_INBOUND_MESSAGES_PER_WEBHOOK"),
        ("max_inbound_message_chars", 0, "MAX_INBOUND_MESSAGE_CHARS"),
    ],
)
def test_inbound_limit_settings_are_validated(field, value, message):
    settings = config.Settings.from_env()

    errors, _ = replace(settings, **{field: value}).validation()

    assert any(message in error for error in errors)


def test_dotenv_loader_reads_explicit_application_root(monkeypatch, tmp_path):
    package = tmp_path / "AgendaRelay"
    package.mkdir()
    (package / ".env").write_text("APP_ENV=production\n", encoding="utf-8")
    monkeypatch.delenv("APP_ENV", raising=False)

    config._load_runtime_environment(package)

    assert config.os.environ["APP_ENV"] == "production"


def test_dotenv_loader_handles_windows_powershell_utf8_bom(monkeypatch, tmp_path):
    package = tmp_path / "AgendaRelay"
    package.mkdir()
    (package / ".env").write_text("\ufeffAPP_ENV=production\n", encoding="utf-8")
    monkeypatch.delenv("APP_ENV", raising=False)

    config._load_runtime_environment(package)

    assert config.os.environ["APP_ENV"] == "production"


def test_frozen_setup_writes_configuration_beside_executable(monkeypatch, tmp_path):
    package = tmp_path / "AgendaRelay"
    package.mkdir()
    monkeypatch.setattr(standalone.sys, "frozen", True, raising=False)
    monkeypatch.setattr(standalone.sys, "executable", str(package / "AgendaRelay.exe"))
    setup_calls = []
    monkeypatch.setattr("scheduler.setup.interactive_setup", lambda directory: setup_calls.append(directory) or 0)

    try:
        standalone.main(["--setup"])
    except SystemExit as exc:
        assert exc.code == 0

    assert setup_calls == [package]


def test_standalone_does_not_start_worker_when_web_listener_cannot_bind(monkeypatch):
    worker_calls = []
    worker_started = threading.Event()
    store_closed = []
    service = SimpleNamespace(run_due_jobs=lambda: (worker_calls.append(True), worker_started.set()))
    app = SimpleNamespace(extensions={
        "settings": SimpleNamespace(is_production=False),
        "scheduling": service,
        "store": SimpleNamespace(close=lambda: store_closed.append(True)),
    })
    monkeypatch.setattr(standalone, "create_app", lambda: app)
    monkeypatch.setenv("PORT", "5019")
    monkeypatch.setenv("BIND_HOST", "127.0.0.1")
    monkeypatch.setattr(
        standalone,
        "create_server",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("address already in use")),
        raising=False,
    )

    def fail_after_worker_starts(*_args, **_kwargs):
        assert worker_started.wait(timeout=1), "the worker should expose the pre-bind startup race"
        raise OSError("address already in use")

    monkeypatch.setattr(standalone, "serve", fail_after_worker_starts, raising=False)
    with pytest.raises(OSError, match="address already in use"):
        standalone.main([])

    assert worker_calls == []
    assert store_closed == [True]


def test_standalone_binds_before_worker_and_closes_resources(monkeypatch):
    events = []
    worker_started = threading.Event()
    service = SimpleNamespace(
        run_due_jobs=lambda: (events.append("worker"), worker_started.set())
    )
    store = SimpleNamespace(close=lambda: events.append("store_closed"))
    app = SimpleNamespace(extensions={
        "settings": SimpleNamespace(is_production=False),
        "scheduling": service,
        "store": store,
    })

    class FakeServer:
        def run(self):
            assert worker_started.wait(timeout=1)
            events.append("server_run")

        def close(self):
            events.append("server_closed")

    def create_server(*_args, **kwargs):
        events.append("server_bound")
        assert kwargs["threads"] == 2
        assert kwargs["connection_limit"] == 20
        return FakeServer()

    monkeypatch.setattr(standalone, "create_app", lambda: app)
    monkeypatch.setattr(standalone, "create_server", create_server)
    monkeypatch.setenv("PORT", "5019")
    monkeypatch.setenv("BIND_HOST", "127.0.0.1")
    monkeypatch.setenv("WAITRESS_THREADS", "1")
    monkeypatch.setenv("WAITRESS_CONNECTION_LIMIT", "1")

    standalone.main([])

    assert events.index("server_bound") < events.index("worker") < events.index("server_run")
    assert events[-2:] == ["server_closed", "store_closed"]
