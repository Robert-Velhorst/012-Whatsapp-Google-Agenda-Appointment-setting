import sqlite3
from datetime import timedelta

from scheduler.migrations import MIGRATIONS
from scheduler.store import Store, utc_now


def test_reminder_without_approved_template_becomes_manual(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    store.schedule_job("default", "appointment_reminder", "manual-test", (utc_now() - timedelta(minutes=1)).isoformat(), {"appointment_id": 999})
    result = app.extensions["scheduling"].run_due_jobs()
    # Missing/non-booked appointments are cancelled, not falsely sent.
    assert result["claimed"] == 1 and result["sent"] == 0


def test_unknown_job_fails_truthfully(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    store.schedule_job("default", "unknown", "unknown-test", (utc_now() - timedelta(minutes=1)).isoformat(), {})
    result = app.extensions["scheduling"].run_due_jobs()
    assert result["failed"] == 1


def test_retention_purge_runs_while_automation_is_paused(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    settings = app.extensions["settings"]
    sender = "31612345678"
    received_at = (utc_now() - timedelta(days=settings.data_retention_days + 1)).isoformat()
    store.record_inbound("default", "wamid.expired", sender, "old scheduling message", received_at)
    store.record_inbound("default", "wamid.current", sender, "current scheduling message", utc_now().isoformat())
    store.schedule_job("default", "appointment_reminder", "paused-reminder", utc_now().isoformat(), {"appointment_id": 999})
    store.set_state("default", "automation_paused", "true")

    result = app.extensions["scheduling"].run_due_jobs()

    assert [item["external_id"] for item in store.recent_messages("default", sender)] == ["wamid.current"]
    assert result["claimed"] == 0
    with store.connect() as db:
        first_purge_audits = db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE workspace_id=? AND action='privacy.retention_purge'",
            ("default",),
        ).fetchone()[0]

    app.extensions["scheduling"].run_due_jobs()

    with store.connect() as db:
        second_purge_audits = db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE workspace_id=? AND action='privacy.retention_purge'",
            ("default",),
        ).fetchone()[0]
    assert first_purge_audits == 1
    assert second_purge_audits == first_purge_audits


def test_v4_database_migration_adds_retention_indexes(tmp_path):
    database_path = tmp_path / "v4.sqlite3"
    db = sqlite3.connect(database_path)
    db.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    for version, sql in MIGRATIONS[:4]:
        db.executescript(sql)
        db.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)", (version, "2026-01-01T00:00:00+00:00"))
    db.executemany(
        "INSERT INTO inbound_messages(workspace_id,external_id,sender,body_ciphertext,received_at) VALUES(?,?,?,?,?)",
        (("default", f"old-{index}", "31612345678", "encrypted-test", "2026-01-01T00:00:00+00:00") for index in range(5)),
    )
    db.executemany(
        "INSERT INTO rate_events(workspace_id,subject,action,created_at) VALUES(?,?,?,?)",
        (("default", "31612345678", "test", "2026-01-01T00:00:00+00:00") for _ in range(5)),
    )
    db.commit()
    db.close()

    store = Store(database_path)
    try:
        with store.connect() as db:
            applied_versions = {row[0] for row in db.execute("SELECT version FROM schema_migrations")}
            message_count = db.execute("SELECT COUNT(*) FROM inbound_messages WHERE workspace_id='default'").fetchone()[0]
            rate_event_count = db.execute("SELECT COUNT(*) FROM rate_events WHERE workspace_id='default'").fetchone()[0]
            message_plan = db.execute(
                "EXPLAIN QUERY PLAN DELETE FROM inbound_messages WHERE workspace_id=? AND received_at<?",
                ("default", "9999-12-31T00:00:00+00:00"),
            ).fetchall()
            rate_plan = db.execute(
                "EXPLAIN QUERY PLAN DELETE FROM rate_events WHERE workspace_id=? AND created_at<?",
                ("default", "9999-12-31T00:00:00+00:00"),
            ).fetchall()
    finally:
        store.close()

    assert 5 in applied_versions
    assert message_count == 5
    assert rate_event_count == 5
    assert any("idx_messages_retention" in row[3] for row in message_plan)
    assert any("idx_rate_retention" in row[3] for row in rate_plan)
