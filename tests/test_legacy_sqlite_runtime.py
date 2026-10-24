import json
import os
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

from scheduler.cli import _online_backup
from scheduler.store import Store

ROOT = Path(__file__).resolve().parents[1]


def test_database_created_by_original_engine_survives_upgrade_and_backup(tmp_path):
    prepared = json.loads((ROOT / ".runtime" / "sqlite-runtime.json").read_text(encoding="utf-8"))
    database = tmp_path / "previous-engine.sqlite3"
    environment = os.environ.copy()
    environment.pop("LD_LIBRARY_PATH", None)
    environment.pop("PYTHONPATH", None)
    create_legacy = """
import json,sqlite3,sys
sys.path.insert(0,sys.argv[1])
from scheduler.migrations import migrate
connection=sqlite3.connect(sys.argv[2])
try:
 migrate(connection,'2026-01-01T00:00:00+00:00')
 connection.execute('INSERT INTO workspaces(id,name,timezone,created_at) VALUES(?,?,?,?)',('legacy','Synthetic legacy workspace','Europe/Amsterdam','then'))
 connection.commit()
finally:connection.close()
print(json.dumps({'sqlite':sqlite3.sqlite_version}))
"""
    original = json.loads(subprocess.check_output(
        [prepared["original_executable"], "-I", "-c", create_legacy, str(ROOT), str(database)],
        text=True, env=environment, timeout=30,
    ))
    assert tuple(map(int, original["sqlite"].split("."))) < (3, 54, 1)
    assert sqlite3.sqlite_version == "3.54.1"
    with closing(Store(database)) as storage:
        storage.set_state("legacy", "runtime_upgrade_fixture", "preserved")
        with storage.connect() as db:
            assert db.execute("SELECT name FROM workspaces WHERE id='legacy'").fetchone()[0] == "Synthetic legacy workspace"
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    backup = tmp_path / "current-engine-backup.sqlite3"
    _online_backup(database, backup)
    with closing(Store(backup)) as restored:
        with restored.connect() as db:
            assert db.execute("SELECT name FROM workspaces WHERE id='legacy'").fetchone()[0] == "Synthetic legacy workspace"
            assert db.execute("SELECT value FROM system_state WHERE workspace_id='legacy' AND key='runtime_upgrade_fixture'").fetchone()[0] == "preserved"
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
