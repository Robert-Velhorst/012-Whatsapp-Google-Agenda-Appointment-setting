import sqlite3
from pathlib import Path

import pytest

from scheduler.database_runtime import require_current_sqlite, runtime_versions
from scheduler.store import Store


def test_actual_sqlite_engine_and_health(app_bundle):
    require_current_sqlite()
    assert sqlite3.sqlite_version == "3.54.1"
    app, _, _ = app_bundle
    actual = app.test_client().get("/api/health").get_json()["runtime"]
    assert actual == runtime_versions()
    assert actual["python"] == "3.15.1"
    assert actual["sqlite"] == "3.54.1"


def test_old_engine_is_rejected_before_opening_data(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 53, 1))
    target = tmp_path / "new-data" / "agenda.sqlite3"
    with pytest.raises(RuntimeError, match="SQLite 3.54.1"):
        Store(target)
    assert not target.parent.exists()
