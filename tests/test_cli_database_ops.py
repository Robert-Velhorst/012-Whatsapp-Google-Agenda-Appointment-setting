from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from scheduler.cli import (
    _database_is_healthy_and_writable,
    _online_backup,
    _restore_database,
    _validate_app_database,
    main,
)
from scheduler.migrations import MIGRATIONS


def test_database_doctor_checks_integrity_and_write_lock(app_bundle, tmp_path):
    app, _, _ = app_bundle
    database = app.extensions["settings"].database_path

    assert _database_is_healthy_and_writable(database)

    broken = tmp_path / "not-a-database.sqlite3"
    broken.write_text("not sqlite", encoding="utf-8")
    assert not _database_is_healthy_and_writable(broken)


def test_doctor_exits_nonzero_when_database_is_unhealthy(monkeypatch, tmp_path, capsys):
    app = SimpleNamespace(extensions={
        "settings": SimpleNamespace(database_path=tmp_path / "unhealthy.sqlite3"),
        "store": object(),
        "scheduling": SimpleNamespace(readiness=lambda: {"ready": True}),
    })
    monkeypatch.setattr("scheduler.cli.create_app", lambda: app)
    monkeypatch.setattr("scheduler.cli._database_is_healthy_and_writable", lambda _path: False)

    exit_code = main(["doctor"])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert report["ready"] is True
    assert report["database"]["writable"] is False


def test_support_bundle_does_not_overwrite_existing_output(monkeypatch, tmp_path, capsys):
    output = tmp_path / "existing-support.zip"
    original = b"preserve the earlier diagnostic bundle"
    output.write_bytes(original)
    monkeypatch.setattr(
        "scheduler.cli.os.link",
        lambda _temporary, destination: (_ for _ in ()).throw(
            FileExistsError(17, "File exists", str(destination))
        ),
    )
    app = SimpleNamespace(extensions={
        "settings": SimpleNamespace(
            app_env="test", timezone="Europe/Amsterdam", workspace_id="default", database_path=tmp_path / "agenda.sqlite3",
        ),
        "store": SimpleNamespace(recent_audit=lambda *_args: []),
        "scheduling": SimpleNamespace(readiness=lambda: {"ready": False}),
    })
    monkeypatch.setattr("scheduler.cli.create_app", lambda: app)

    exit_code = main(["support-bundle", "--output", str(output)])

    assert exit_code == 2
    assert output.read_bytes() == original
    assert "already exists" in capsys.readouterr().err.lower()


def test_online_backup_is_consistent_and_refuses_live_database_overwrite(app_bundle, tmp_path):
    app, _, _ = app_bundle
    database = app.extensions["settings"].database_path
    output = tmp_path / "backup.sqlite3"

    with pytest.raises(ValueError, match="live database"):
        _online_backup(database, database)

    _online_backup(database, output)
    with closing(sqlite3.connect(output)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone() == (max(version for version, _ in MIGRATIONS),)


def test_backup_default_is_inside_database_data_directory(monkeypatch, tmp_path, capsys):
    database = tmp_path / "data" / "scheduler.sqlite3"
    app = SimpleNamespace(extensions={
        "settings": SimpleNamespace(database_path=database),
        "store": object(),
        "scheduling": object(),
    })
    captured = {}
    monkeypatch.setattr("scheduler.cli.create_app", lambda: app)
    monkeypatch.setattr("scheduler.cli._online_backup", lambda _source, destination: captured.setdefault("output", destination))

    assert main(["backup"]) == 0

    output = captured["output"]
    assert output.parent == database.parent / "backups"
    assert output.name.startswith("agenda-relay-")
    assert output.suffix == ".sqlite3"
    assert str(output) in capsys.readouterr().out


def test_online_backup_does_not_overwrite_an_existing_backup(app_bundle, tmp_path):
    app, _, _ = app_bundle
    database = app.extensions["settings"].database_path
    output = tmp_path / "existing-backup.sqlite3"
    original = b"preserve this existing backup"
    output.write_bytes(original)

    with pytest.raises(FileExistsError):
        _online_backup(database, output)

    assert output.read_bytes() == original


def test_restore_stages_backup_and_keeps_verified_safety_copy(app_bundle, tmp_path):
    app, _, _ = app_bundle
    database = app.extensions["settings"].database_path
    store = app.extensions["store"]
    backup = tmp_path / "restore-source.sqlite3"
    _online_backup(database, backup)

    with closing(sqlite3.connect(database)) as connection:
        connection.execute("INSERT INTO workspaces(id,name,timezone,created_at) VALUES ('restore-test','before','UTC','now')")
        connection.commit()
    with closing(sqlite3.connect(backup)) as connection:
        connection.execute("INSERT INTO workspaces(id,name,timezone,created_at) VALUES ('restore-test','after','UTC','now')")
        connection.commit()

    safety = _restore_database(backup, database, store)

    assert safety is not None and safety.is_file()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT name FROM workspaces WHERE id='restore-test'").fetchone() == ("after",)
    with closing(sqlite3.connect(safety)) as connection:
        assert connection.execute("SELECT name FROM workspaces WHERE id='restore-test'").fetchone() == ("before",)


def test_restore_cli_recovers_corrupt_live_database_and_preserves_original_bytes(
    app_bundle, tmp_path, monkeypatch, capsys,
):
    app, _, _ = app_bundle
    settings = app.extensions["settings"]
    backup = tmp_path / "known-good.sqlite3"
    _online_backup(settings.database_path, backup)

    damaged_database = tmp_path / "damaged-live.sqlite3"
    damaged_bytes = b"SQLite header and pages are damaged; preserve these bytes"
    damaged_database.write_bytes(damaged_bytes)
    monkeypatch.setattr(
        "scheduler.cli.Settings.from_env",
        lambda *_args, **_kwargs: replace(settings, database_path=damaged_database),
    )

    exit_code = main(["restore", str(backup), "--confirm", "RESTORE"])

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["previous_database"]
    assert Path(result["previous_database"]).read_bytes() == damaged_bytes
    with closing(sqlite3.connect(damaged_database)) as connection:
        assert _validate_app_database(connection)


def test_restore_refuses_idle_open_wal_database(app_bundle, tmp_path):
    app, _, _ = app_bundle
    database = app.extensions["settings"].database_path
    backup = tmp_path / "idle-wal-backup.sqlite3"
    _online_backup(database, backup)
    with closing(sqlite3.connect(database)) as checkpoint:
        assert checkpoint.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
    external_connection = sqlite3.connect(database)
    assert external_connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    external_connection.execute("SELECT id FROM workspaces").fetchall()
    wal_path = Path(f"{database}-wal")
    assert wal_path.exists() and wal_path.stat().st_size == 0

    try:
        with pytest.raises(RuntimeError, match="stop all web and worker processes"):
            _restore_database(backup, database, app.extensions["store"])
    finally:
        external_connection.close()


def test_restore_rejects_non_app_sqlite_database(app_bundle, tmp_path):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    invalid = tmp_path / "foreign.sqlite3"
    with closing(sqlite3.connect(invalid)) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")

    with pytest.raises(ValueError, match="application schema"):
        _restore_database(invalid, app.extensions["settings"].database_path, store)


def test_app_database_validation_rejects_latest_version_without_migration_history(tmp_path):
    invalid = tmp_path / "forged-latest-version.sqlite3"
    with closing(sqlite3.connect(invalid)) as connection:
        connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 'now')",
            (max(version for version, _ in MIGRATIONS),),
        )

        assert not _validate_app_database(connection)


def test_backup_and_restore_reject_forged_latest_version_without_touching_live_database(app_bundle, tmp_path):
    app, _, _ = app_bundle
    database = app.extensions["settings"].database_path
    store = app.extensions["store"]
    invalid = tmp_path / "forged-latest-version.sqlite3"
    with closing(sqlite3.connect(invalid)) as connection:
        connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 'now')",
            (max(version for version, _ in MIGRATIONS),),
        )

    with pytest.raises(ValueError, match="Source database failed integrity or schema validation"):
        _online_backup(invalid, tmp_path / "rejected-backup.sqlite3")
    with pytest.raises(ValueError, match="application schema validation"):
        _restore_database(invalid, database, store)

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT id FROM workspaces LIMIT 1").fetchone() is not None


def test_app_database_validation_rejects_missing_core_table(app_bundle):
    app, _, _ = app_bundle
    database = app.extensions["settings"].database_path
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("DROP TABLE background_jobs")
        connection.commit()

        assert not _validate_app_database(connection)


def test_app_database_validation_rejects_foreign_key_orphans(app_bundle):
    app, _, _ = app_bundle
    database = app.extensions["settings"].database_path
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "INSERT INTO contacts(workspace_id,sender,timezone,language,consent_status,created_at,updated_at) "
            "VALUES ('missing-workspace','contact','UTC','en','implicit_inbound','now','now')"
        )
        connection.commit()

        assert not _validate_app_database(connection)
