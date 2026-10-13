from pathlib import Path

import pytest
from dotenv import dotenv_values
from werkzeug.security import check_password_hash

from scheduler.setup import initialize, interactive_setup


def test_setup_generates_distinct_secrets_and_valid_password(tmp_path):
    (tmp_path / ".env.example").write_text(Path(".env.example").read_text())
    target = initialize(tmp_path, "a private operator password")
    config = dotenv_values(target)
    keys = [config[name] for name in ("FLASK_SECRET_KEY", "ADMIN_API_TOKEN", "DATA_ENCRYPTION_KEY", "WHATSAPP_VERIFY_TOKEN")]
    assert len(set(keys)) == 4 and all(len(key) >= 48 for key in keys)
    assert check_password_hash(config["ADMIN_PASSWORD_HASH"], "a private operator password")
    assert "a private operator password" not in target.read_text()
    assert config["APP_ENV"] == "development"
    assert config["AUTO_BOOK_CONFIRMED"] == "false"


def test_setup_never_overwrites_existing_keys(tmp_path):
    (tmp_path / ".env").write_text("existing configuration")
    with pytest.raises(FileExistsError):
        initialize(tmp_path, "a private operator password")
    assert (tmp_path / ".env").read_text() == "existing configuration"


def test_setup_rejects_short_password_without_writing(tmp_path):
    with pytest.raises(ValueError):
        initialize(tmp_path, "short")
    assert not (tmp_path / ".env").exists()


def test_setup_mismatch_does_not_write(tmp_path, monkeypatch):
    answers = iter(["a private operator password", "a different operator password"])
    monkeypatch.setattr("scheduler.setup.getpass.getpass", lambda _: next(answers))
    assert interactive_setup(tmp_path) == 1
    assert not (tmp_path / ".env").exists()
