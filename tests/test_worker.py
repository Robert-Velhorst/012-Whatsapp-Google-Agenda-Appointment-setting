import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from scheduler.migrations import MIGRATIONS
from scheduler.calendar import GoogleCalendar
from scheduler.store import Store, utc_now
from .conftest import post_webhook, webhook


def _stale_booking(app):
    post_webhook(app.test_client(), webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    post_webhook(app.test_client(), webhook("wamid.2", body="The second one works for me"))
    appointment_id = store.dashboard("default")["items"][0]["appointment_id"]
    appointment = store.claim_booking("default", appointment_id)
    assert appointment is not None
    with store.connect() as db:
        start_at = datetime.fromisoformat(appointment["start_at"]) + timedelta(days=3)
        end_at = datetime.fromisoformat(appointment["end_at"]) + timedelta(days=3)
        db.execute(
            "UPDATE appointments SET start_at=?,end_at=? WHERE workspace_id=? AND id=?",
            (start_at.isoformat(), end_at.isoformat(), "default", appointment_id),
        )
        db.execute("UPDATE appointments SET updated_at='2020-01-01T00:00:00+00:00' WHERE id=?", (appointment_id,))
    assert store.recover_stale_bookings("default", "2021-01-01T00:00:00+00:00") == 1
    return store, appointment_id, appointment


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


@pytest.mark.parametrize("payload_json", ["{", "[]", '"not-an-object"'])
def test_malformed_due_job_does_not_block_later_jobs(app_bundle, payload_json):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    now = utc_now()
    malformed_id = store.schedule_job(
        "default", "appointment_reminder", "malformed-payload",
        (now - timedelta(minutes=2)).isoformat(), {"appointment_id": 1},
    )
    valid_id = store.schedule_job(
        "default", "unknown", "valid-payload-after-malformed",
        (now - timedelta(minutes=1)).isoformat(), {},
    )
    with store.connect() as db:
        db.execute("UPDATE background_jobs SET payload_json=? WHERE id=?", (payload_json, malformed_id))

    claimed = store.claim_due_jobs("default", now.isoformat())

    assert [job["id"] for job in claimed] == [valid_id]
    with store.connect() as db:
        malformed = db.execute(
            "SELECT status,last_error FROM background_jobs WHERE id=?", (malformed_id,),
        ).fetchone()
        audit = db.execute(
            "SELECT action,detail_json FROM audit_events WHERE entity_id=? ORDER BY id DESC LIMIT 1",
            (str(malformed_id),),
        ).fetchone()
    assert malformed["status"] == "failed"
    assert "payload" in malformed["last_error"].lower()
    assert audit["action"] == "job.failed"
    assert json.loads(audit["detail_json"])["error"] == "Malformed job payload"


def test_worker_recovers_stale_booking_and_request_state_atomically(app_bundle):
    app, _, _ = app_bundle
    store, appointment_id, appointment = _stale_booking(app)

    assert store.get_appointment("default", appointment_id)["status"] == "manual_required"
    request = store.request_detail("default", appointment["request_id"])
    assert request["status"] == "failed"
    transition = [
        event for event in request["audit"]
        if event["action"] == "request.transition" and event["detail"].get("reason") == "stale_calendar_booking"
    ]
    assert len(transition) == 1


def test_stale_booking_reconciliation_restores_verified_event_without_sending_whatsapp(app_bundle):
    app, calendar, whatsapp = app_bundle
    store, appointment_id, appointment = _stale_booking(app)
    calendar.events[appointment_id] = {"id": f"event-{appointment_id}", "htmlLink": f"https://calendar.google.com/event/{appointment_id}"}
    sent_before = len(whatsapp.sent)

    result = app.extensions["scheduling"].reconcile_stale_booking(appointment_id)

    assert result["status"] == "booked"
    recovered = store.get_appointment("default", appointment_id)
    assert recovered["status"] == "booked"
    assert recovered["google_event_id"] == f"event-{appointment_id}"
    assert store.request_detail("default", appointment["request_id"])["status"] == "booked"
    assert len(whatsapp.sent) == sent_before
    reminder_offset = app.extensions["settings"].reminder_minutes_before
    assert any(job["dedupe_key"] == f"reminder:{appointment_id}:{reminder_offset}" for job in store.dashboard("default")["jobs"])


def test_stale_booking_not_found_becomes_explicitly_retryable(app_bundle):
    app, calendar, _ = app_bundle
    store, appointment_id, _ = _stale_booking(app)

    result = app.extensions["scheduling"].reconcile_stale_booking(appointment_id)

    assert result["status"] == "failed"
    assert result["retryable"] is True
    assert store.get_appointment("default", appointment_id)["status"] == "failed"
    assert calendar.created == []
    assert store.get_appointment("default", appointment_id)["booking_attempt"] == 1

    booked = app.extensions["scheduling"].book_appointment(appointment_id)
    assert booked["status"] == "booked"
    assert len(calendar.created) == 1
    retry = store.get_appointment("default", appointment_id)
    assert retry["booking_attempt"] == 2
    assert GoogleCalendar._event_id("default", appointment_id, 2) != GoogleCalendar._event_id("default", appointment_id, 1)
    assert calendar.created[0]["booking_attempt"] == 2


def test_stale_booking_lookup_failure_does_not_change_manual_state(app_bundle, auth_headers):
    app, calendar, _ = app_bundle
    store, appointment_id, _ = _stale_booking(app)
    calendar.lookup_error = RuntimeError("private calendar response")

    response = app.test_client().post(f"/api/appointments/{appointment_id}/reconcile", headers=auth_headers)

    assert response.status_code == 502
    assert b"private calendar response" not in response.data
    assert store.get_appointment("default", appointment_id)["status"] == "manual_required"


def test_operator_can_reconcile_stale_booking_from_csrf_protected_dashboard(app_bundle):
    app, _, _ = app_bundle
    store, appointment_id, appointment = _stale_booking(app)
    client = app.test_client()
    with client.session_transaction() as current:
        current["operator_authenticated"] = True
        current["csrf_token"] = "booking-reconcile-csrf"

    page = client.get(f"/?view=scheduling&request={appointment['request_id']}")
    assert page.status_code == 200
    assert b"Calendar booking needs verification" in page.data
    assert b"Check Google Calendar" in page.data

    rejected = client.post(f"/actions/appointments/{appointment_id}/reconcile")
    assert rejected.status_code == 403
    accepted = client.post(
        f"/actions/appointments/{appointment_id}/reconcile",
        data={"csrf_token": "booking-reconcile-csrf"},
    )
    assert accepted.status_code == 302
    assert store.get_appointment("default", appointment_id)["status"] == "failed"


def test_retention_purge_runs_while_automation_is_paused(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    settings = app.extensions["settings"]
    sender = "31612345678"
    received_at = (utc_now() - timedelta(days=settings.data_retention_days + 1)).isoformat()
    assert store.accept_inbound_message(
        "default", "wamid.expired", sender, "old scheduling message", received_at,
        max_per_sender=10, max_total=10,
    ) == "accepted"
    assert store.accept_inbound_message(
        "default", "wamid.current", sender, "current scheduling message", utc_now().isoformat(),
        max_per_sender=10, max_total=10,
    ) == "accepted"
    with store.connect() as db:
        db.execute(
            "INSERT INTO whatsapp_delivery_events(workspace_id,provider_message_id,status,provider_timestamp,error_code,received_at) "
            "VALUES(?,?,?,?,?,?)",
            ("default", "wamid.old", "delivered", received_at, None, received_at),
        )
        db.execute(
            "INSERT INTO audit_events(workspace_id,actor,action,entity_type,entity_id,detail_json,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            ("default", "whatsapp_webhook", "whatsapp.delivery_status", "provider_message", "wamid.old", "{}", received_at),
        )
    store.schedule_job("default", "appointment_reminder", "paused-reminder", utc_now().isoformat(), {"appointment_id": 999})
    store.set_state("default", "automation_paused", "true")

    result = app.extensions["scheduling"].run_due_jobs()

    assert [item["external_id"] for item in store.recent_messages("default", sender)] == ["wamid.current"]
    assert result["claimed"] == 0
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM whatsapp_delivery_events").fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action='whatsapp.delivery_status'",
        ).fetchone()[0] == 0
        purge_event = db.execute(
            "SELECT detail_json FROM audit_events WHERE workspace_id=? AND action='privacy.retention_purge'",
            ("default",),
        ).fetchone()
    assert json.loads(purge_event[0])["delivery_events_deleted"] == 1
    assert json.loads(purge_event[0])["delivery_audit_events_deleted"] == 1
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


def test_scheduling_retention_removes_aged_resolved_records_but_preserves_future_and_recovery_work(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    client = app.test_client()
    for index in range(6):
        assert post_webhook(
            client,
            webhook(f"wamid.retention.{index}", body="Could we schedule a 30 minute call tomorrow?"),
        ).status_code == 200
    items = sorted(store.dashboard("default")["items"], key=lambda item: item["id"])
    failed, expired_proposal, future_booked, completed_booked, cancelled, failed_appointment = items
    old = (utc_now() - timedelta(days=100)).isoformat()
    past_start = (utc_now() - timedelta(days=100)).isoformat()
    past_end = (utc_now() - timedelta(days=100) + timedelta(minutes=30)).isoformat()
    future_start = (utc_now() + timedelta(days=30)).isoformat()
    future_end = (utc_now() + timedelta(days=30, minutes=30)).isoformat()
    with store.connect() as db:
        db.execute(
            "UPDATE scheduling_requests SET status='failed',updated_at=? WHERE id=?",
            (old, failed["id"]),
        )
        db.execute("UPDATE proposals SET created_at=? WHERE id=?", (old, failed["proposal_id"]))
        db.execute(
            "UPDATE scheduling_requests SET status='needs_clarification',updated_at=? WHERE id=?",
            (old, expired_proposal["id"]),
        )
        db.execute(
            "UPDATE proposals SET status='expired',sent_at=? WHERE id=?",
            (old, expired_proposal["proposal_id"]),
        )
        db.execute(
            "UPDATE scheduling_requests SET status='booked',updated_at=? WHERE id=?",
            (old, future_booked["id"]),
        )
        db.execute("UPDATE proposals SET status='confirmed' WHERE id=?", (future_booked["proposal_id"],))
        future_cursor = db.execute(
            "INSERT INTO appointments(workspace_id,request_id,proposal_id,start_at,end_at,timezone,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,'booked',?,?)",
            (
                "default", future_booked["id"], future_booked["proposal_id"], future_start,
                future_end, "Europe/Amsterdam", old, old,
            ),
        )
        db.execute(
            "UPDATE scheduling_requests SET status='booked',updated_at=? WHERE id=?",
            (old, completed_booked["id"]),
        )
        db.execute("UPDATE proposals SET status='confirmed' WHERE id=?", (completed_booked["proposal_id"],))
        completed_cursor = db.execute(
            "INSERT INTO appointments(workspace_id,request_id,proposal_id,start_at,end_at,timezone,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,'booked',?,?)",
            (
                "default", completed_booked["id"], completed_booked["proposal_id"], past_start,
                past_end, "Europe/Amsterdam", old, old,
            ),
        )
        db.execute(
            "UPDATE scheduling_requests SET status='cancelled',updated_at=? WHERE id=?",
            (old, cancelled["id"]),
        )
        cancelled_cursor = db.execute(
            "INSERT INTO appointments(workspace_id,request_id,proposal_id,start_at,end_at,timezone,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,'cancelled',?,?)",
            (
                "default", cancelled["id"], cancelled["proposal_id"], past_start,
                past_end, "Europe/Amsterdam", old, old,
            ),
        )
        db.execute(
            "UPDATE scheduling_requests SET status='failed',updated_at=? WHERE id=?",
            (old, failed_appointment["id"]),
        )
        db.execute(
            "INSERT INTO appointments(workspace_id,request_id,proposal_id,start_at,end_at,timezone,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,'failed',?,?)",
            (
                "default", failed_appointment["id"], failed_appointment["proposal_id"], past_start,
                past_end, "Europe/Amsterdam", old, old,
            ),
        )

    store.schedule_job(
        "default", "appointment_reminder", "retention-completed-booking",
        (utc_now() + timedelta(days=1)).isoformat(),
        {"appointment_id": int(completed_cursor.lastrowid)},
    )
    store.schedule_job(
        "default", "appointment_reminder", "retention-future-booking",
        (utc_now() + timedelta(days=1)).isoformat(),
        {"appointment_id": int(future_cursor.lastrowid)},
    )
    store.audit(
        "default", "test", "appointment.booked", "appointment", int(completed_cursor.lastrowid),
        {"synthetic_record": True},
    )

    result = app.extensions["scheduling"].run_due_jobs()

    assert result["scheduling_records_deleted"] == 11
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM scheduling_requests WHERE id=?", (failed["id"],)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM proposals WHERE id=?", (failed["proposal_id"],)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM scheduling_requests WHERE id=?", (expired_proposal["id"],)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM proposals WHERE id=?", (expired_proposal["proposal_id"],)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM appointments WHERE request_id=?", (future_booked["id"],)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM scheduling_requests WHERE id=?", (future_booked["id"],)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM appointments WHERE request_id=?", (completed_booked["id"],)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM scheduling_requests WHERE id=?", (completed_booked["id"],)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM proposals WHERE id=?", (completed_booked["proposal_id"],)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM appointments WHERE request_id=?", (cancelled["id"],)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM appointments WHERE request_id=?", (failed_appointment["id"],)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM scheduling_requests WHERE id=?", (failed_appointment["id"],)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM proposals WHERE id=?", (failed_appointment["proposal_id"],)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM background_jobs WHERE dedupe_key='retention-completed-booking'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM background_jobs WHERE dedupe_key='retention-future-booking'").fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action='appointment.booked' AND entity_id=?",
            (str(completed_cursor.lastrowid),),
        ).fetchone()[0] == 1
        purge = db.execute(
            "SELECT detail_json FROM audit_events WHERE action='privacy.scheduling_retention_purge'",
        ).fetchone()
    assert json.loads(purge[0])["appointments_deleted"] == 2
    assert json.loads(purge[0])["google_events_deleted"] == 0
    assert json.loads(purge[0])["audit_history_deleted"] == 0


def test_scheduling_retention_rolls_back_deletions_when_audit_write_fails(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    assert post_webhook(client, webhook()).status_code == 200
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    assert post_webhook(client, webhook("wamid.retention-confirmed", body="1")).status_code == 200
    appointment = store.dashboard("default")["items"][0]
    appointment_id = appointment["appointment_id"]
    assert app.extensions["scheduling"].book_appointment(appointment_id)["status"] == "booked"
    old = (utc_now() - timedelta(days=100)).isoformat()
    with store.connect() as db:
        db.execute(
            "UPDATE appointments SET start_at=?,end_at=?,updated_at=? WHERE workspace_id=? AND id=?",
            (old, old, old, "default", appointment_id),
        )
        db.execute(
            "CREATE TRIGGER reject_scheduling_retention_audit BEFORE INSERT ON audit_events "
            "WHEN NEW.action='privacy.scheduling_retention_purge' BEGIN "
            "SELECT RAISE(ABORT, 'retention audit unavailable'); END"
        )
    job_id = store.schedule_job(
        "default", "appointment_reminder", "retention-audit-rollback",
        (utc_now() + timedelta(days=1)).isoformat(), {"appointment_id": appointment_id},
    )
    assert job_id is not None

    with pytest.raises(sqlite3.IntegrityError, match="retention audit unavailable"):
        store.purge_terminal_scheduling_records("default", 90, 168)

    with store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM appointments WHERE workspace_id=? AND id=? AND status='booked'",
            ("default", appointment_id),
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM scheduling_requests WHERE workspace_id=? AND id=?",
            ("default", appointment["id"]),
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM proposals WHERE workspace_id=? AND id=?",
            ("default", appointment["proposal_id"]),
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM background_jobs WHERE workspace_id=? AND id=?",
            ("default", job_id),
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE workspace_id=? AND action='privacy.scheduling_retention_purge'",
            ("default",),
        ).fetchone()[0] == 0


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


def test_contact_deletion_rolls_back_when_privacy_audit_fails(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    contact_id = store.upsert_contact("default", "31612345678", "Europe/Amsterdam")
    assert store.accept_inbound_message(
        "default", "wamid.contact-delete", "31612345678", "synthetic message", utc_now().isoformat(),
        max_per_sender=10, max_total=10,
    ) == "accepted"
    with store.connect() as db:
        db.execute(
            "CREATE TRIGGER reject_contact_delete_audit BEFORE INSERT ON audit_events "
            "WHEN NEW.action='privacy.contact_deleted' BEGIN "
            "SELECT RAISE(ABORT, 'contact deletion audit unavailable'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="contact deletion audit unavailable"):
        store.delete_contact("default", contact_id)

    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM contacts WHERE workspace_id='default' AND id=?", (contact_id,)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM inbound_messages WHERE workspace_id='default' AND external_id='wamid.contact-delete'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='privacy.contact_deleted'").fetchone()[0] == 0


def test_message_retention_purge_rolls_back_when_audit_fails(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    old = (utc_now() - timedelta(days=100)).isoformat()
    assert store.accept_inbound_message(
        "default", "wamid.retention-rollback", "31612345678", "synthetic message", old,
        max_per_sender=10, max_total=10,
    ) == "accepted"
    with store.connect() as db:
        db.execute(
            "CREATE TRIGGER reject_message_retention_audit BEFORE INSERT ON audit_events "
            "WHEN NEW.action='privacy.retention_purge' BEGIN "
            "SELECT RAISE(ABORT, 'message retention audit unavailable'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="message retention audit unavailable"):
        store.purge_expired("default", 90)

    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM inbound_messages WHERE external_id='wamid.retention-rollback'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='privacy.retention_purge'").fetchone()[0] == 0


def test_proposal_expiry_rolls_back_when_audit_fails(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    assert post_webhook(client, webhook()).status_code == 200
    store = app.extensions["store"]
    proposal_id = store.dashboard("default")["items"][0]["proposal_id"]
    app.extensions["scheduling"].send_proposal(proposal_id)
    old = (utc_now() - timedelta(days=100)).isoformat()
    with store.connect() as db:
        db.execute("UPDATE proposals SET sent_at=? WHERE workspace_id='default' AND id=?", (old, proposal_id))
        db.execute(
            "CREATE TRIGGER reject_proposal_expiry_audit BEFORE INSERT ON audit_events "
            "WHEN NEW.action='proposals.expired' BEGIN "
            "SELECT RAISE(ABORT, 'proposal expiry audit unavailable'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="proposal expiry audit unavailable"):
        store.expire_stale_proposals("default", utc_now().isoformat())

    with store.connect() as db:
        assert db.execute("SELECT status FROM proposals WHERE workspace_id='default' AND id=?", (proposal_id,)).fetchone()[0] == "sent"
        assert db.execute("SELECT status FROM scheduling_requests WHERE workspace_id='default' AND id=(SELECT request_id FROM proposals WHERE id=?)", (proposal_id,)).fetchone()[0] == "awaiting_confirmation"
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='proposals.expired'").fetchone()[0] == 0
