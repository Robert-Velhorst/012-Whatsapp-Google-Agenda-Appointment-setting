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
        # The migration sequence grows over time; leave headroom for contended SQLite DDL.
        results = [future.result(timeout=30) for future in futures]

    assert len(results) == worker_count
    with closing(sqlite3.connect(database_path)) as db:
        versions = {row[0] for row in db.execute("SELECT version FROM schema_migrations")}
        columns = [row[1] for row in db.execute("PRAGMA table_info(proposals)")]
        appointment_columns = [row[1] for row in db.execute("PRAGMA table_info(appointments)")]
    assert versions == {version for version, _ in MIGRATIONS}
    assert columns.count("booking_token_ciphertext") == 1
    assert appointment_columns.count("booking_attempt") == 1


def test_v6_appointments_get_safe_initial_booking_attempts(tmp_path):
    database_path = tmp_path / "v6.sqlite3"
    db = sqlite3.connect(database_path)
    db.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    for version, sql in MIGRATIONS[:6]:
        db.executescript(sql)
        db.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, "2026-01-01T00:00:00+00:00"),
        )
    statuses = ["pending_approval", "booking", "booked", "manual_required", "failed", "cancelled"]
    for index, status in enumerate(statuses, start=1):
        db.execute(
            "INSERT INTO appointments(workspace_id,request_id,proposal_id,start_at,end_at,timezone,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            ("default", index, index, "2030-01-01T10:00:00+00:00", "2030-01-01T10:30:00+00:00", "UTC", status, "2030-01-01", "2030-01-01"),
        )
    db.commit()

    migrate(db, "2026-01-02T00:00:00+00:00")

    attempts = dict(db.execute("SELECT status,booking_attempt FROM appointments"))
    assert attempts == {
        "pending_approval": 0,
        "booking": 1,
        "booked": 1,
        "manual_required": 1,
        "failed": 1,
        "cancelled": 0,
    }
    db.close()
