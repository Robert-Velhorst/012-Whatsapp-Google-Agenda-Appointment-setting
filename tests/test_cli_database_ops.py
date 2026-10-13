from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from scheduler.cli import (
    _database_is_healthy_and_writable,
    _online_backup,
    _restore_database,
)


def test_database_doctor_checks_integrity_and_write_lock(app_bundle, tmp_path):
    app, _, _ = app_bundle
    database = app.extensions["settings"].database_path

    assert _database_is_healthy_and_writable(database)

    broken = tmp_path / "not-a-database.sqlite3"
    broken.write_text("not sqlite", encoding="utf-8")
    assert not _database_is_healthy_and_writable(broken)


def test_online_backup_is_consistent_and_refuses_live_database_overwrite(app_bundle, tmp_path):
    app, _, _ = app_bundle
    database = app.extensions["settings"].database_path
    output = tmp_path / "backup.sqlite3"

    with pytest.raises(ValueError, match="live database"):
        _online_backup(database, database)

    _online_backup(database, output)
    with closing(sqlite3.connect(output)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone() == (5,)


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


def test_restore_rejects_non_app_sqlite_database(app_bundle, tmp_path):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    invalid = tmp_path / "foreign.sqlite3"
    with closing(sqlite3.connect(invalid)) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")

    with pytest.raises(ValueError, match="application schema"):
        _restore_database(invalid, app.extensions["settings"].database_path, store)
