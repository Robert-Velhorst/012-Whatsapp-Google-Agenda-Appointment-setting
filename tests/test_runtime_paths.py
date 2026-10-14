from __future__ import annotations

from pathlib import Path

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


def test_dotenv_loader_reads_explicit_application_root(monkeypatch, tmp_path):
    package = tmp_path / "AgendaRelay"
    package.mkdir()
    (package / ".env").write_text("APP_ENV=production\n", encoding="utf-8")
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
