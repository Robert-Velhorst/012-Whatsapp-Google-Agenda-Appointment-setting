from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor

import pytest

from scheduler.migrations import MIGRATIONS, migrate


@pytest.mark.parametrize("existing_schema", [False, True])
def test_concurrent_processes_apply_each_migration_once(tmp_path, existing_schema):
    database_path = tmp_path / "concurrent-migrations.sqlite3"
    if existing_schema:
        connection = sqlite3.connect(database_path)
        connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        connection.executescript(MIGRATIONS[0][1])
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, ?)",
            ("2026-01-01T00:00:00+00:00",),
        )
        connection.commit()
        connection.close()

    worker_count = 8
    barrier = threading.Barrier(worker_count)

    def apply_pending_migrations():
        db = sqlite3.connect(database_path, timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        try:
            barrier.wait(timeout=5)
            return migrate(db, "2026-01-02T00:00:00+00:00")
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [pool.submit(apply_pending_migrations) for _ in range(worker_count)]
        results = [future.result(timeout=15) for future in futures]

    assert len(results) == worker_count
    with closing(sqlite3.connect(database_path)) as db:
        versions = {row[0] for row in db.execute("SELECT version FROM schema_migrations")}
        columns = [row[1] for row in db.execute("PRAGMA table_info(proposals)")]
    assert versions == {version for version, _ in MIGRATIONS}
    assert columns.count("booking_token_ciphertext") == 1
