from datetime import timedelta

from scheduler.store import utc_now


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
