from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

from scheduler.crypto import CryptoBox
from scheduler.crypto_rotation import rotate_encryption_bundle
from scheduler.cli import main as cli_main
from scheduler import standalone


NEW_KEY = "new-key-for-test-" + "n" * 64


def _seed_sensitive_rows(app):
    store = app.extensions["store"]
    store.ensure_workspace("default", "Test", "Europe/Amsterdam")
    contact_id = store.upsert_contact("default", "31612345678", "Europe/Amsterdam", display_name="Test")
    assert store.accept_inbound_message(
        "default", "wamid.rotate", "31612345678", "private message", "2026-10-14T10:00:00+00:00",
        max_per_sender=10, max_total=10,
    ) == "accepted"
    request_id = store.create_request(
        "default", contact_id, "wamid.rotate", "Appointment", 30,
        "Europe/Amsterdam", "2026-10-20T10:00:00+02:00", 0.95,
    )
    proposal_id, booking_token = store.create_proposal(
        "default", request_id, "Prepared private reply", ["2026-10-20T10:00:00+02:00"],
    )
    return proposal_id, booking_token


def test_rotation_bundle_reencrypts_database_and_google_token_without_touching_inputs(app_bundle, tmp_path):
    app, _, _ = app_bundle
    settings = app.extensions["settings"]
    proposal_id, booking_token = _seed_sensitive_rows(app)
    old_box = CryptoBox(settings.data_encryption_key)
    token_path = tmp_path / "google-token.json"
    token_plain = '{"refresh_token":"private-refresh-token"}'
    token_path.write_text(old_box.encrypt(token_plain), encoding="utf-8")
    token_before = token_path.read_bytes()
    app.extensions["store"].close()
    database_before = settings.database_path.read_bytes()

    output = tmp_path / "rotated"
    result = rotate_encryption_bundle(
        settings.database_path, token_path, output,
        settings.data_encryption_key, NEW_KEY,
    )

    new_box = CryptoBox(NEW_KEY)
    assert result["encrypted_database_values_rotated"] == 3
    assert result["google_token_file"] == "google-token.json"
    assert settings.database_path.read_bytes() == database_before
    assert token_path.read_bytes() == token_before
    with closing(sqlite3.connect(output / "scheduler.sqlite3")) as db:
        message = db.execute("SELECT body_ciphertext FROM inbound_messages").fetchone()[0]
        reply, token = db.execute(
            "SELECT reply_ciphertext, booking_token_ciphertext FROM proposals WHERE id=?", (proposal_id,)
        ).fetchone()
    assert new_box.decrypt_strict(message) == "private message"
    assert new_box.decrypt_strict(reply) == "Prepared private reply"
    assert new_box.decrypt_strict(token) == booking_token
    rotated_token = (output / "google-token.json").read_text(encoding="utf-8")
    assert new_box.decrypt_strict(rotated_token) == token_plain
    assert json.loads((output / "rotation.json").read_text(encoding="utf-8"))["database_sha256"] == hashlib.sha256(
        (output / "scheduler.sqlite3").read_bytes()
    ).hexdigest()


def test_rotation_rejects_wrong_old_key_without_publishing_output(app_bundle, tmp_path):
    app, _, _ = app_bundle
    settings = app.extensions["settings"]
    _seed_sensitive_rows(app)
    app.extensions["store"].close()
    before = settings.database_path.read_bytes()
    output = tmp_path / "must-not-exist"

    with pytest.raises(ValueError, match="cannot be decrypted"):
        rotate_encryption_bundle(settings.database_path, tmp_path / "missing-token.json", output, "wrong-old-key", NEW_KEY)

    assert not output.exists()
    assert settings.database_path.read_bytes() == before


def test_rotation_refuses_existing_output_and_weak_or_reused_new_key(app_bundle, tmp_path):
    app, _, _ = app_bundle
    settings = app.extensions["settings"]
    _seed_sensitive_rows(app)
    app.extensions["store"].close()
    output = tmp_path / "already-there"
    output.mkdir()

    with pytest.raises(FileExistsError, match="already exists"):
        rotate_encryption_bundle(settings.database_path, tmp_path / "missing-token.json", output, settings.data_encryption_key, NEW_KEY)
    with pytest.raises(ValueError, match="at least 64"):
        rotate_encryption_bundle(settings.database_path, tmp_path / "missing-token.json", tmp_path / "weak", settings.data_encryption_key, "short")
    with pytest.raises(ValueError, match="must differ"):
        rotate_encryption_bundle(settings.database_path, tmp_path / "missing-token.json", tmp_path / "same", settings.data_encryption_key, settings.data_encryption_key)


def test_rotation_rejects_malformed_token_before_creating_output(app_bundle, tmp_path):
    app, _, _ = app_bundle
    settings = app.extensions["settings"]
    _seed_sensitive_rows(app)
    token_path = tmp_path / "google-token.json"
    token_path.write_text(CryptoBox(settings.data_encryption_key).encrypt("not-json"), encoding="utf-8")
    app.extensions["store"].close()
    output = tmp_path / "invalid-token-output"

    with pytest.raises(ValueError, match="valid JSON"):
        rotate_encryption_bundle(settings.database_path, token_path, output, settings.data_encryption_key, NEW_KEY)

    assert not output.exists()


def test_rotation_cli_uses_environment_keys_and_does_not_print_them(app_bundle, tmp_path, monkeypatch, capsys):
    app, _, _ = app_bundle
    settings = app.extensions["settings"]
    _seed_sensitive_rows(app)
    app.extensions["store"].close()
    monkeypatch.setenv("DATABASE_PATH", str(settings.database_path))
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "missing-token.json"))
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", settings.data_encryption_key)
    monkeypatch.setenv("NEW_DATA_ENCRYPTION_KEY", NEW_KEY)
    output = tmp_path / "cli-rotated"

    assert cli_main(["rotate-encryption-key", "--output-dir", str(output)]) == 0

    stdout = capsys.readouterr().out
    result = json.loads(stdout)
    assert result["output_directory"] == str(output.resolve())
    assert settings.data_encryption_key not in stdout
    assert NEW_KEY not in stdout
    assert (output / "scheduler.sqlite3").is_file()
    assert not (output / "google-token.json").exists()


def test_standalone_binary_dispatches_operator_cli(monkeypatch, tmp_path):
    calls = []

    def fake_cli(arguments):
        calls.append(arguments)
        return 7

    monkeypatch.setattr("scheduler.cli.main", fake_cli)
    output = tmp_path / "rotated"

    result = standalone.main(["rotate-encryption-key", "--output-dir", str(output)])

    assert result == 7
    assert calls == [["rotate-encryption-key", "--output-dir", str(output)]]

