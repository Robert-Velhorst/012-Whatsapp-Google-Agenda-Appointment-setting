import sqlite3
import threading
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from scheduler.calendar import CalendarUnavailable

from .conftest import post_webhook, webhook


def test_message_to_proposal_to_confirmation_to_calendar_event(app_bundle, auth_headers):
    app, calendar, whatsapp = app_bundle
    client = app.test_client()
    assert post_webhook(client, webhook()).get_json()["proposals"] == 1
    item = client.get("/api/requests", headers=auth_headers).get_json()["items"][0]

    sent = client.post(f"/api/proposals/{item['proposal_id']}/send", headers=auth_headers)
    assert sent.status_code == 200
    assert len(whatsapp.sent) == 1

    confirmed = post_webhook(client, webhook("wamid.2", body="The second one works for me"))
    assert confirmed.get_json()["confirmations"] == 1
    item = client.get("/api/requests", headers=auth_headers).get_json()["items"][0]
    assert item["status"] == "slot_confirmed"
    assert item["appointment_status"] == "pending_approval"

    booked = client.post(f"/api/appointments/{item['appointment_id']}/book", headers=auth_headers)
    assert booked.status_code == 200
    assert booked.get_json()["status"] == "booked"
    assert len(calendar.created) == 1
    assert len(whatsapp.sent) == 2
    final = client.get("/api/requests", headers=auth_headers).get_json()["items"][0]
    assert final["status"] == "booked"
    assert final["google_event_link"].startswith("https://calendar.google.com/")

    repeat = client.post(f"/api/appointments/{item['appointment_id']}/book", headers=auth_headers)
    assert repeat.status_code == 200 and repeat.get_json()["idempotent"] is True
    assert len(calendar.created) == 1


def test_booking_api_sanitizes_calendar_availability_errors_and_persists_no_provider_detail(app_bundle, auth_headers):
    app, calendar, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    post_webhook(client, webhook("wamid.2", body="The second one works for me"))
    item = store.dashboard("default")["items"][0]
    secret_provider_detail = "PRIVATE_CALENDAR_PROVIDER_SECRET"

    def fail_availability(*_args, **_kwargs):
        raise RuntimeError(secret_provider_detail)

    calendar.is_slot_available = fail_availability
    response = client.post(f"/api/appointments/{item['appointment_id']}/book", headers=auth_headers)

    assert response.status_code == 502
    assert response.get_json()["error"] == {
        "code": "calendar_booking_unverified",
        "message": "Google Calendar availability could not be verified. No event was created; review Calendar before retrying.",
        "retryable": True,
    }
    assert secret_provider_detail not in response.get_data(as_text=True)
    with store.connect() as db:
        appointment = db.execute("SELECT error_text FROM appointments WHERE id=?", (item["appointment_id"],)).fetchone()
        audit = db.execute(
            "SELECT detail_json FROM audit_events ORDER BY id DESC LIMIT 6",
        ).fetchall()
    assert secret_provider_detail not in appointment["error_text"]
    assert secret_provider_detail not in " ".join(row["detail_json"] for row in audit)
    assert any('"error_class": "RuntimeError"' in row["detail_json"] for row in audit)


def test_booking_api_returns_conflict_when_calendar_changes_are_paused(app_bundle, auth_headers):
    app, _, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    post_webhook(client, webhook("wamid.2", body="The second one works for me"))
    item = store.dashboard("default")["items"][0]
    store.set_state("default", "automation_paused", "true", "test")

    response = client.post(f"/api/appointments/{item['appointment_id']}/book", headers=auth_headers)

    assert response.status_code == 409
    assert response.get_json()["error"] == {
        "code": "automation_paused",
        "message": "Calendar changes are disabled while automation is paused.",
        "retryable": False,
    }


def test_booking_api_does_not_misclassify_unexpected_runtime_errors_as_paused(app_bundle, auth_headers, monkeypatch):
    app, _, _ = app_bundle
    secret_detail = "PRIVATE_INTERNAL_BOOKING_DETAIL"

    def fail_booking(*_args, **_kwargs):
        raise RuntimeError(secret_detail)

    monkeypatch.setattr(app.extensions["scheduling"], "book_appointment", fail_booking)
    response = app.test_client().post("/api/appointments/999/book", headers=auth_headers)

    assert response.status_code == 500
    assert response.get_json()["error"] == {
        "code": "booking_failed",
        "message": "Calendar booking could not be completed. Verify the appointment state before retrying.",
        "retryable": False,
    }
    assert secret_detail not in response.get_data(as_text=True)


def test_proposal_api_returns_conflict_when_outbound_automation_is_paused(app_bundle, auth_headers):
    app, _, whatsapp = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    proposal_id = store.dashboard("default")["items"][0]["proposal_id"]
    store.set_state("default", "automation_paused", "true", "test")

    response = client.post(f"/api/proposals/{proposal_id}/send", headers=auth_headers)

    assert response.status_code == 409
    assert response.get_json()["error"] == {
        "code": "automation_paused",
        "message": "WhatsApp sending is disabled while automation is paused.",
        "retryable": False,
    }
    assert whatsapp.sent == []


def test_booking_api_returns_conflict_when_slot_became_busy(app_bundle, auth_headers):
    app, calendar, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    post_webhook(client, webhook("wamid.2", body="The second one works for me"))
    item = store.dashboard("default")["items"][0]
    calendar.is_slot_available = lambda *_args, **_kwargs: False

    response = client.post(f"/api/appointments/{item['appointment_id']}/book", headers=auth_headers)

    assert response.status_code == 409
    assert response.get_json()["error"] == {
        "code": "calendar_slot_unavailable",
        "message": "The selected time has since become busy. No calendar event was created; review the request and offer new times.",
        "retryable": False,
    }
    assert calendar.created == []


def test_booking_api_marks_ambiguous_calendar_create_non_retryable(app_bundle, auth_headers):
    app, calendar, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    post_webhook(client, webhook("wamid.2", body="The second one works for me"))
    item = store.dashboard("default")["items"][0]
    secret_provider_detail = "PRIVATE_CALENDAR_CREATE_RESPONSE"
    calendar.create_event = lambda _appointment: (_ for _ in ()).throw(RuntimeError(secret_provider_detail))

    response = client.post(f"/api/appointments/{item['appointment_id']}/book", headers=auth_headers)

    assert response.status_code == 502
    assert response.get_json()["error"] == {
        "code": "calendar_booking_unverified",
        "message": "Google Calendar may have accepted this event. Verify Calendar before retrying the booking.",
        "retryable": False,
    }
    assert secret_provider_detail not in response.get_data(as_text=True)
    assert store.get_appointment("default", item["appointment_id"])["status"] == "manual_required"


def test_request_creation_rolls_back_when_audit_insert_fails(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    contact_id = store.upsert_contact("default", "31612345678", "Europe/Amsterdam")
    with store.connect() as db:
        db.execute(
            "CREATE TRIGGER reject_request_audit BEFORE INSERT ON audit_events "
            "WHEN NEW.action='request.detected' BEGIN "
            "SELECT RAISE(ABORT, 'request audit unavailable'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="request audit unavailable"):
        store.create_request(
            "default", contact_id, "atomic-request-1", "Consultation", 30,
            "Europe/Amsterdam", "2030-01-07T10:00:00+01:00", 0.9,
        )

    with store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM scheduling_requests WHERE source_message_id='atomic-request-1'"
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action='request.detected'"
        ).fetchone()[0] == 0


def test_contact_request_creation_is_atomic_and_records_the_expected_state(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]

    contact_id, request_id = store.create_contact_request(
        "default", "31612345679", "Europe/Amsterdam", "nl", "Synthetic contact",
        "wamid.atomic-contact-request", "Afspraak", 45, "2030-01-08T09:00:00+01:00", 0.91,
    )

    contact = store.get_contact("default", contact_id)
    request = store.request_detail("default", request_id)
    assert contact["sender"] == "31612345679"
    assert contact["language"] == "nl"
    assert contact["display_name"] == "Synthetic contact"
    assert request["contact_id"] == contact_id
    assert request["status"] == "detected"
    assert store.recent_audit("default", 1)[0]["action"] == "request.detected"


def test_contact_request_creation_rolls_back_contact_when_request_audit_fails(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    with store.connect() as db:
        db.execute(
            "CREATE TRIGGER reject_request_audit BEFORE INSERT ON audit_events "
            "WHEN NEW.action='request.detected' BEGIN "
            "SELECT RAISE(ABORT, 'request audit unavailable'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="request audit unavailable"):
        store.create_contact_request(
            "default", "31612345680", "Europe/Amsterdam", "nl", None,
            "wamid.atomic-contact-request-fail", "Afspraak", 45,
            "2030-01-08T09:00:00+01:00", 0.91,
        )

    with store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM contacts WHERE workspace_id='default' AND sender='31612345680'"
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM scheduling_requests WHERE source_message_id='wamid.atomic-contact-request-fail'"
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action='request.detected'"
        ).fetchone()[0] == 0


def test_contact_language_update_and_request_creation_are_atomic(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    contact_id = store.upsert_contact(
        "default", "31612345682", "Europe/Amsterdam", display_name="Previous name",
    )

    request_id = store.update_contact_and_create_request(
        "default", contact_id, "nl", "Updated name", "wamid.contact-update-request",
        "Afspraak", 45, "Europe/Amsterdam", "2030-01-08T09:00:00+01:00", 0.91,
    )

    contact = store.get_contact("default", contact_id)
    assert contact["language"] == "nl"
    assert contact["display_name"] == "Updated name"
    assert store.request_detail("default", request_id)["contact_id"] == contact_id
    assert store.recent_audit("default", 1)[0]["action"] == "request.detected"


def test_contact_language_update_rolls_back_when_request_audit_fails(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    contact_id = store.upsert_contact(
        "default", "31612345683", "Europe/Amsterdam", "en", "Previous name",
    )
    with store.connect() as db:
        db.execute(
            "CREATE TRIGGER reject_request_audit BEFORE INSERT ON audit_events "
            "WHEN NEW.action='request.detected' BEGIN "
            "SELECT RAISE(ABORT, 'request audit unavailable'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="request audit unavailable"):
        store.update_contact_and_create_request(
            "default", contact_id, "nl", "Updated name", "wamid.contact-update-request-fail",
            "Afspraak", 45, "Europe/Amsterdam", "2030-01-08T09:00:00+01:00", 0.91,
        )

    contact = store.get_contact("default", contact_id)
    assert contact["language"] == "en"
    assert contact["display_name"] == "Previous name"
    with store.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM scheduling_requests WHERE source_message_id='wamid.contact-update-request-fail'"
        ).fetchone()[0] == 0


def test_contact_upsert_without_new_language_preserves_existing_language(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    contact_id = store.upsert_contact("default", "31612345681", "Europe/Amsterdam", "nl")

    updated_id = store.upsert_contact(
        "default", "31612345681", "Europe/Amsterdam", display_name="Synthetic contact",
    )

    assert updated_id == contact_id
    assert store.get_contact("default", contact_id)["language"] == "nl"


def test_scheduling_webhook_batches_contact_language_request_and_audit_write(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    statements = []
    connection = store._local.connection.connection
    connection.set_trace_callback(statements.append)
    try:
        response = post_webhook(app.test_client(), webhook())
    finally:
        connection.set_trace_callback(None)

    assert response.status_code == 200
    assert response.get_json()["proposals"] == 1
    # Includes the durable completion marker after the contact/request and proposal writes.
    assert sum(statement.strip().upper() == "COMMIT" for statement in statements) == 5


def test_non_scheduling_webhook_does_not_reset_existing_contact_language(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    contact_id = store.upsert_contact("default", "31612345678", "Europe/Amsterdam", "nl")

    result = post_webhook(app.test_client(), webhook("wamid.non-scheduling", body="Hello there"))

    assert result.status_code == 200
    assert store.get_contact("default", contact_id)["language"] == "nl"


def test_booking_does_not_create_event_if_selected_slot_is_now_busy(app_bundle):
    app, calendar, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    item = app.extensions["store"].dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    post_webhook(client, webhook("wamid.2", body="1"))
    item = app.extensions["store"].dashboard("default")["items"][0]
    calendar.is_slot_available = lambda start, end: False

    with pytest.raises(CalendarUnavailable, match="selected time has since become busy"):
        app.extensions["scheduling"].book_appointment(item["appointment_id"])

    assert calendar.created == []
    appointment = app.extensions["store"].get_appointment("default", item["appointment_id"])
    assert appointment["status"] == "failed"


@pytest.mark.parametrize("failure_point", ["provider_response_lost", "local_commit_failed"])
def test_ambiguous_calendar_create_requires_reconciliation_before_retry(app_bundle, failure_point):
    app, calendar, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    post_webhook(client, webhook("wamid.2", body="The second one works for me"))
    appointment_id = store.dashboard("default")["items"][0]["appointment_id"]
    create_event = calendar.create_event
    mark_booked = store.mark_booked

    if failure_point == "provider_response_lost":
        def create_then_timeout(appointment):
            create_event(appointment)
            raise TimeoutError("Google accepted the event, but the response was lost")

        calendar.create_event = create_then_timeout
        with pytest.raises(CalendarUnavailable, match="may have accepted"):
            app.extensions["scheduling"].book_appointment(appointment_id)
    else:
        def fail_local_commit(*args, **kwargs):
            raise sqlite3.IntegrityError("local booking commit failed after event creation")

        store.mark_booked = fail_local_commit
        with pytest.raises(CalendarUnavailable, match="needs reconciliation"):
            app.extensions["scheduling"].book_appointment(appointment_id)

    assert store.get_appointment("default", appointment_id)["status"] == "manual_required"
    calendar.create_event = create_event
    store.mark_booked = mark_booked
    recovered = app.extensions["scheduling"].reconcile_stale_booking(appointment_id)
    assert recovered["status"] == "booked"
    assert store.get_appointment("default", appointment_id)["status"] == "booked"
    assert len(calendar.created) == 1
    retry = app.extensions["scheduling"].book_appointment(appointment_id)
    assert retry["idempotent"] is True
    assert len(calendar.created) == 1


def test_failed_booking_reconciliation_advances_hai_appointment_cursor(app_bundle):
    app, calendar, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    scheduling = app.extensions["scheduling"]
    item = store.dashboard("default")["items"][0]
    scheduling.send_proposal(item["proposal_id"])
    post_webhook(client, webhook("wamid.2", body="The second one works for me"))
    appointment_id = store.dashboard("default")["items"][0]["appointment_id"]
    original_mark_booked = store.mark_booked

    def fail_local_commit(*args, **kwargs):
        raise sqlite3.IntegrityError("synthetic local commit failure after provider create")

    store.mark_booked = fail_local_commit
    with pytest.raises(CalendarUnavailable, match="needs reconciliation"):
        scheduling.book_appointment(appointment_id)
    store.mark_booked = original_mark_booked
    assert store.get_appointment("default", appointment_id)["status"] == "manual_required"

    calendar.events.pop(appointment_id)
    _, cursor = store.hai_feed("default")
    result = scheduling.reconcile_stale_booking(appointment_id)
    assert result["status"] == "failed"

    items, _ = store.hai_feed("default", cursor)
    assert len(items) == 1
    assert items[0]["status"] == "failed"
    assert items[0]["appointment_status"] == "failed"


def test_hai_feed_cursor_pages_equal_timestamp_rows_without_gaps_or_duplicates(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    for index in range(4):
        post_webhook(client, webhook(f"wamid.page.{index}", body="Could we schedule a meeting tomorrow?"))
    store = app.extensions["store"]
    timestamp = "2026-10-15T12:00:00+00:00"
    with store.connect() as db:
        db.execute("UPDATE scheduling_requests SET updated_at=?", (timestamp,))

    cursor = store._encode_feed_cursor(timestamp, 0)
    seen_ids = []
    while True:
        items, next_cursor = store.hai_feed("default", cursor, limit=2)
        if not items:
            break
        seen_ids.extend(item["id"] for item in items)
        cursor = next_cursor

    assert seen_ids == [1, 2, 3, 4]


def test_idempotent_booking_retry_repairs_missing_reminder_job(app_bundle):
    app, calendar, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    post_webhook(client, webhook("wamid.2", body="The second one works for me"))
    appointment_id = store.dashboard("default")["items"][0]["appointment_id"]
    scheduling = app.extensions["scheduling"]
    scheduling.settings = replace(app.extensions["settings"], reminder_minutes_before=5)
    schedule_job = store.schedule_job

    def fail_reminder_once(workspace_id, job_type, dedupe_key, run_at, payload):
        if job_type == "appointment_reminder":
            raise sqlite3.OperationalError("temporary reminder queue failure")
        return schedule_job(workspace_id, job_type, dedupe_key, run_at, payload)

    store.schedule_job = fail_reminder_once
    with pytest.raises(sqlite3.OperationalError, match="reminder queue failure"):
        scheduling.book_appointment(appointment_id)
    assert store.get_appointment("default", appointment_id)["status"] == "booked"
    store.schedule_job = schedule_job

    retried = scheduling.book_appointment(appointment_id)

    assert retried["idempotent"] is True
    assert len(calendar.created) == 1
    with store.connect() as db:
        reminder_count = db.execute(
            "SELECT COUNT(*) FROM background_jobs WHERE workspace_id='default' AND job_type='appointment_reminder' AND dedupe_key=?",
            (f"reminder:{appointment_id}:5",),
        ).fetchone()[0]
    assert reminder_count == 1


def test_public_booking_link_requires_consent(app_bundle, auth_headers):
    app, _, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    proposal = store.get_proposal("default", item["proposal_id"])
    token = proposal["booking_token"]
    assert client.get(f"/book/{token}").status_code == 200
    with client.session_transaction() as current:
        csrf = current["csrf_token"]
    assert client.post(f"/book/{token}", data={"slot": "0"}).status_code == 403
    rejected = client.post(f"/book/{token}", data={"csrf_token": csrf, "slot": "0"})
    assert rejected.status_code == 400
    accepted = client.post(f"/book/{token}", data={"csrf_token": csrf, "slot": "0", "consent": "yes"})
    assert accepted.status_code == 200
    assert b"Your selection was received" in accepted.data
    assert b"operator will add it" in accepted.data


def test_busy_public_slot_does_not_consume_proposal(app_bundle):
    app, calendar, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    proposal = store.get_proposal("default", item["proposal_id"])
    client.get(f"/book/{proposal['booking_token']}")
    with client.session_transaction() as current:
        csrf = current["csrf_token"]
    app.extensions["scheduling"].settings = replace(app.extensions["settings"], auto_book_confirmed=True)
    calendar.is_slot_available = lambda start, end: False

    response = client.post(f"/book/{proposal['booking_token']}", data={"csrf_token": csrf, "slot": "0", "consent": "yes"})

    assert response.status_code == 400
    assert b"choose another proposed time" in response.data
    assert store.get_proposal("default", item["proposal_id"])["status"] == "sent"
    assert store.dashboard("default")["items"][0].get("appointment_id") is None


def test_public_auto_booking_reports_calendar_and_whatsapp_result(app_bundle):
    app, calendar, whatsapp = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    proposal = store.get_proposal("default", item["proposal_id"])
    client.get(f"/book/{proposal['booking_token']}")
    with client.session_transaction() as current:
        csrf = current["csrf_token"]
    app.extensions["scheduling"].settings = replace(app.extensions["settings"], auto_book_confirmed=True)

    response = client.post(f"/book/{proposal['booking_token']}", data={"csrf_token": csrf, "slot": "0", "consent": "yes"})

    assert response.status_code == 200
    assert b"Your appointment is confirmed" in response.data
    assert b"added to the Google Calendar" in response.data
    assert b"sent through WhatsApp" in response.data
    assert len(calendar.created) == 1
    assert len(whatsapp.sent) == 2


def test_public_booking_hides_provider_error_details(app_bundle, caplog):
    app, calendar, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    proposal = store.get_proposal("default", item["proposal_id"])
    client.get(f"/book/{proposal['booking_token']}")
    with client.session_transaction() as current:
        csrf = current["csrf_token"]
    app.extensions["scheduling"].settings = replace(app.extensions["settings"], auto_book_confirmed=True)
    calendar.is_slot_available = lambda start, end: True
    calendar.create_event = lambda appointment: (_ for _ in ()).throw(
        RuntimeError("PRIVATE_PROVIDER_RESPONSE access_token=do-not-disclose")
    )

    response = client.post(
        f"/book/{proposal['booking_token']}",
        data={"csrf_token": csrf, "slot": "0", "consent": "yes"},
    )

    assert response.status_code == 400
    assert b"confirm this selection" in response.data
    assert b"PRIVATE_PROVIDER_RESPONSE" not in response.data
    assert b"do-not-disclose" not in response.data
    assert "PRIVATE_PROVIDER_RESPONSE" not in caplog.text
    assert "do-not-disclose" not in caplog.text
    appointment = store.dashboard("default")["items"][0]
    assert appointment["appointment_status"] == "manual_required"


def test_cancelling_appointment_does_not_cancel_prefix_matching_reminder(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    post_webhook(client, webhook("wamid.2", body="The second one works for me"))
    appointment = store.dashboard("default")["items"][0]
    appointment_id = appointment["appointment_id"]
    prefix_matching_id = int(f"{appointment_id}0")
    store.schedule_job("default", "appointment_reminder", "cancel-target", "2099-01-01T00:00:00+00:00", {"appointment_id": appointment_id})
    store.schedule_job("default", "appointment_reminder", "cancel-other", "2099-01-01T00:00:00+00:00", {"appointment_id": prefix_matching_id})
    store.schedule_job("default", "unrelated_job", "cancel-unrelated-type", "2099-01-01T00:00:00+00:00", {"appointment_id": appointment_id})

    assert store.cancel_appointment("default", appointment_id, "operator") is True

    with store.connect() as db:
        statuses = {
            row["dedupe_key"]: row["status"]
            for row in db.execute(
                "SELECT dedupe_key,status FROM background_jobs WHERE workspace_id='default' AND dedupe_key IN ('cancel-target','cancel-other','cancel-unrelated-type')"
            )
        }
    assert statuses == {"cancel-target": "cancelled", "cancel-other": "queued", "cancel-unrelated-type": "queued"}


def _book_calendar_appointment(app):
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    service = app.extensions["scheduling"]
    service.send_proposal(item["proposal_id"])
    post_webhook(client, webhook("wamid.2", body="The second one works for me"))
    appointment_id = store.dashboard("default")["items"][0]["appointment_id"]
    service.book_appointment(appointment_id)
    return appointment_id


def test_cancellation_is_blocked_after_reminder_worker_claims_send(app_bundle, auth_headers, monkeypatch):
    app, calendar, whatsapp = app_bundle
    appointment_id = _book_calendar_appointment(app)
    store = app.extensions["store"]
    service = app.extensions["scheduling"]
    service.settings = replace(service.settings, whatsapp_reminder_template="appointment_reminder")
    store.schedule_job(
        "default", "appointment_reminder", f"test-reminder:{appointment_id}",
        "2000-01-01T00:00:00+00:00", {"appointment_id": appointment_id},
    )
    worker_at_send = threading.Event()
    allow_send = threading.Event()
    worker_errors = []
    original_rate_limit = service._enforce_rate_limit

    def pause_before_send(sender):
        worker_at_send.set()
        if not allow_send.wait(timeout=5):
            raise TimeoutError("test did not release the reminder sender")
        original_rate_limit(sender)

    monkeypatch.setattr(service, "_enforce_rate_limit", pause_before_send)

    def run_worker():
        try:
            service.run_due_jobs()
        except Exception as exc:  # Captured across the worker thread for deterministic assertions below.
            worker_errors.append(exc)

    worker_thread = threading.Thread(target=run_worker, daemon=True)
    worker_thread.start()
    try:
        assert worker_at_send.wait(timeout=5)
        response = app.test_client().post(f"/api/appointments/{appointment_id}/cancel", headers=auth_headers)
        assert response.status_code == 409
        assert response.get_json()["error"]["code"] == "appointment_not_cancellable"
        assert calendar.cancelled == []
        assert store.get_appointment("default", appointment_id)["status"] == "booked"
    finally:
        allow_send.set()
        worker_thread.join(timeout=5)

    assert not worker_thread.is_alive()
    assert worker_errors == []
    assert len(whatsapp.templates) == 1
    assert store.get_appointment("default", appointment_id)["status"] == "booked"


def test_cancellation_recovery_transitions_advance_hai_feed_cursor(app_bundle):
    app, _, _ = app_bundle
    appointment_id = _book_calendar_appointment(app)
    store = app.extensions["store"]
    _, cursor = store.hai_feed("default")

    assert store.claim_cancellation("default", appointment_id, "operator") is not None
    items, cursor = store.hai_feed("default", cursor)
    assert len(items) == 1
    assert items[0]["appointment_status"] == "cancelling"

    store.mark_cancellation_manual_required("default", appointment_id, "operator")
    items, cursor = store.hai_feed("default", cursor)
    assert len(items) == 1
    assert items[0]["appointment_status"] == "cancel_manual_required"

    store.restore_booked_after_cancellation_check("default", appointment_id, "operator")
    items, cursor = store.hai_feed("default", cursor)
    assert len(items) == 1
    assert items[0]["appointment_status"] == "booked"

    assert store.claim_cancellation("default", appointment_id, "operator") is not None
    _, cursor = store.hai_feed("default", cursor)
    with store.connect() as db:
        db.execute("UPDATE appointments SET updated_at='2000-01-01T00:00:00+00:00' WHERE id=?", (appointment_id,))

    assert store.recover_stale_cancellations("default", "2020-01-01T00:00:00+00:00") == 1
    items, _ = store.hai_feed("default", cursor)
    assert len(items) == 1
    assert items[0]["appointment_status"] == "cancel_manual_required"


def test_proposal_send_claim_advances_hai_feed_cursor(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    proposal_id = store.dashboard("default")["items"][0]["proposal_id"]
    _, cursor = store.hai_feed("default")

    assert store.claim_proposal_send("default", proposal_id)
    items, _ = store.hai_feed("default", cursor)

    assert len(items) == 1
    assert items[0]["proposal_status"] == "sending"


def test_proposal_delivery_recovery_states_advance_hai_feed_cursor(app_bundle):
    app, _, _ = app_bundle
    post_webhook(app.test_client(), webhook())
    store = app.extensions["store"]
    proposal_id = store.dashboard("default")["items"][0]["proposal_id"]
    _, cursor = store.hai_feed("default")

    assert store.claim_proposal_send("default", proposal_id)
    store.mark_proposal_failed("default", proposal_id, "synthetic delivery failure")
    items, cursor = store.hai_feed("default", cursor)
    assert len(items) == 1
    assert items[0]["proposal_status"] == "send_failed"

    assert store.claim_proposal_send("default", proposal_id)
    store.mark_proposal_manual_required("default", proposal_id, "synthetic uncertain delivery")
    items, cursor = store.hai_feed("default", cursor)
    assert len(items) == 1
    assert items[0]["proposal_status"] == "manual_required"

    with store.connect() as db:
        db.execute(
            "UPDATE proposals SET status='sending',sent_at='2000-01-01T00:00:00+00:00' WHERE id=?",
            (proposal_id,),
        )
    assert store.recover_stale_proposal_sends("default", "2020-01-01T00:00:00+00:00") == 1
    items, _ = store.hai_feed("default", cursor)
    assert len(items) == 1
    assert items[0]["proposal_status"] == "manual_required"


def test_proposal_expiry_advances_hai_cursor_when_request_status_is_unchanged(app_bundle):
    app, _, _ = app_bundle
    post_webhook(app.test_client(), webhook())
    store = app.extensions["store"]
    proposal_id = store.dashboard("default")["items"][0]["proposal_id"]
    assert store.claim_proposal_send("default", proposal_id)
    store.mark_proposal_sent("default", proposal_id, "synthetic-message-id")

    with store.connect() as db:
        db.execute(
            "UPDATE scheduling_requests SET status='booked' WHERE id=(SELECT request_id FROM proposals WHERE id=?)",
            (proposal_id,),
        )
        db.execute("UPDATE proposals SET sent_at='2000-01-01T00:00:00+00:00' WHERE id=?", (proposal_id,))
    _, cursor = store.hai_feed("default")

    assert store.expire_stale_proposals("default", "2020-01-01T00:00:00+00:00") == 1
    items, _ = store.hai_feed("default", cursor)

    assert len(items) == 1
    assert items[0]["status"] == "booked"
    assert items[0]["proposal_status"] == "expired"


def test_calendar_cancellation_timeout_is_reconciled_without_losing_state(app_bundle, auth_headers):
    app, calendar, _ = app_bundle
    appointment_id = _book_calendar_appointment(app)
    store = app.extensions["store"]
    assert not app.extensions["scheduling"].is_paused()

    def delete_then_timeout(event_id):
        calendar.cancelled.append(event_id)
        calendar.events.pop(appointment_id, None)
        raise TimeoutError("synthetic response lost after provider deletion")

    calendar.cancel_event = delete_then_timeout
    client = app.test_client()
    cancelled = client.post(f"/api/appointments/{appointment_id}/cancel", headers=auth_headers)

    assert cancelled.status_code == 502, cancelled.get_json()
    assert cancelled.get_json()["error"]["code"] == "calendar_cancellation_unverified"
    assert cancelled.get_json()["error"]["retryable"] is False
    assert "synthetic response lost" not in cancelled.get_data(as_text=True)
    assert store.get_appointment("default", appointment_id)["status"] == "cancel_manual_required"
    assert store.request_detail("default", 1)["status"] == "booked"

    browser = app.test_client()
    with browser.session_transaction() as session:
        session["operator_authenticated"] = True
        session["csrf_token"] = "cancel-reconcile-csrf"
    dashboard = browser.get("/?request=1")
    assert dashboard.status_code == 200
    assert b"Calendar cancellation needs verification" in dashboard.data
    assert b"Check cancellation in Google Calendar" in dashboard.data
    assert b"/reconcile-cancel" in dashboard.data

    reconciled = browser.post(
        f"/actions/appointments/{appointment_id}/reconcile-cancel",
        data={"csrf_token": "cancel-reconcile-csrf"},
    )

    assert reconciled.status_code == 302
    assert store.get_appointment("default", appointment_id)["status"] == "cancelled"
    assert store.request_detail("default", 1)["status"] == "cancelled"


def test_calendar_cancellation_timeout_keeps_live_event_booked_for_explicit_retry(app_bundle, auth_headers):
    app, calendar, _ = app_bundle
    appointment_id = _book_calendar_appointment(app)
    store = app.extensions["store"]
    original_cancel_event = calendar.cancel_event
    calendar.cancel_event = lambda _event_id: (_ for _ in ()).throw(TimeoutError("synthetic timeout before delete"))
    client = app.test_client()

    cancelled = client.post(f"/api/appointments/{appointment_id}/cancel", headers=auth_headers)
    assert cancelled.status_code == 502, cancelled.get_json()
    assert store.get_appointment("default", appointment_id)["status"] == "cancel_manual_required"

    reconciled = client.post(f"/api/appointments/{appointment_id}/reconcile-cancel", headers=auth_headers)

    assert reconciled.status_code == 200
    assert reconciled.get_json()["status"] == "retryable"
    assert store.get_appointment("default", appointment_id)["status"] == "booked"
    assert store.request_detail("default", 1)["status"] == "booked"

    calendar.cancel_event = original_cancel_event
    cancelled = client.post(f"/api/appointments/{appointment_id}/cancel", headers=auth_headers)
    assert cancelled.status_code == 200
    assert store.get_appointment("default", appointment_id)["status"] == "cancelled"


def test_worker_recovers_stale_calendar_cancellation_for_manual_check(app_bundle):
    app, calendar, _ = app_bundle
    appointment_id = _book_calendar_appointment(app)
    store = app.extensions["store"]
    assert store.claim_cancellation("default", appointment_id, "operator") is not None
    with store.connect() as db:
        db.execute(
            "UPDATE appointments SET updated_at='2000-01-01T00:00:00+00:00' WHERE id=?",
            (appointment_id,),
        )

    result = app.extensions["scheduling"].run_due_jobs()

    assert result["recovered_cancellations"] == 1
    assert store.get_appointment("default", appointment_id)["status"] == "cancel_manual_required"
    assert store.request_detail("default", 1)["status"] == "booked"
    assert calendar.cancelled == []


def test_ambiguous_booking_cannot_be_cancelled_without_reconciliation(app_bundle, auth_headers):
    app, calendar, _ = app_bundle
    appointment_id = _book_calendar_appointment(app)
    store = app.extensions["store"]
    with store.connect() as db:
        db.execute(
            "UPDATE appointments SET status='manual_required' WHERE id=?",
            (appointment_id,),
        )

    response = app.test_client().post(
        f"/api/appointments/{appointment_id}/cancel",
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "appointment_not_cancellable"
    assert store.get_appointment("default", appointment_id)["status"] == "manual_required"
    assert calendar.cancelled == []


def test_reschedule_requires_review_then_updates_calendar_and_local_state(app_bundle):
    app, calendar, _ = app_bundle
    appointment_id = _book_calendar_appointment(app)
    store = app.extensions["store"]
    appointment = store.get_appointment("default", appointment_id)
    _, feed_cursor = store.hai_feed("default")
    store.schedule_job(
        "default", "appointment_reminder", f"reminder:{appointment_id}:{app.extensions['scheduling'].settings.reminder_minutes_before}",
        "2099-01-01T00:00:00+00:00", {"appointment_id": appointment_id},
    )
    target_start = datetime.now(ZoneInfo("Europe/Amsterdam")).replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=2)
    if target_start.weekday() >= 5:
        target_start += timedelta(days=7 - target_start.weekday())
    service = app.extensions["scheduling"]

    draft = service.prepare_reschedule(appointment_id, target_start.isoformat())

    assert draft["status"] == "reschedule_pending"
    assert store.get_appointment("default", appointment_id)["start_at"] == appointment["start_at"]
    assert store.get_appointment("default", appointment_id)["pending_start_at"] == target_start.isoformat()
    assert store.request_detail("default", 1)["status"] == "booked"

    result = service.confirm_reschedule(appointment_id)

    updated = store.get_appointment("default", appointment_id)
    assert result["status"] == "booked"
    assert updated["status"] == "booked"
    assert updated["start_at"] == target_start.isoformat()
    assert updated["pending_start_at"] is None
    assert calendar.events[appointment_id]["start"]["dateTime"] == target_start.isoformat()
    with store.connect() as db:
        reminders = db.execute(
            "SELECT status,run_at,dedupe_key FROM background_jobs WHERE workspace_id='default' AND job_type='appointment_reminder' ORDER BY id"
        ).fetchall()
    assert [row["status"] for row in reminders] == ["cancelled", "queued"]
    expected_reminder = target_start.astimezone(ZoneInfo("UTC")) - timedelta(minutes=service.settings.reminder_minutes_before)
    assert reminders[-1]["run_at"] == expected_reminder.isoformat()
    feed_updates, _ = store.hai_feed("default", feed_cursor)
    assert len(feed_updates) == 1
    assert feed_updates[0]["appointment_status"] == "booked"
    assert feed_updates[0]["start_at"] == target_start.isoformat()


def test_reschedule_cannot_be_discarded_while_reminder_is_running(app_bundle):
    app, _, _ = app_bundle
    appointment_id = _book_calendar_appointment(app)
    store = app.extensions["store"]
    service = app.extensions["scheduling"]
    store.schedule_job(
        "default", "appointment_reminder", f"test-reminder:{appointment_id}",
        "2099-01-01T00:00:00+00:00", {"appointment_id": appointment_id},
    )
    target_start = datetime.now(ZoneInfo("Europe/Amsterdam")).replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=6)
    service.prepare_reschedule(appointment_id, target_start.isoformat())

    with store.connect() as db:
        db.execute(
            "UPDATE background_jobs SET status='running' WHERE job_type='appointment_reminder' "
            "AND payload_json LIKE ?",
            (f'%\"appointment_id\": {appointment_id}%',),
        )

    with pytest.raises(ValueError, match="reminder is currently being sent"):
        service.discard_reschedule(appointment_id)

    assert store.get_appointment("default", appointment_id)["status"] == "reschedule_pending"
    with store.connect() as db:
        reminders = db.execute(
            "SELECT status FROM background_jobs WHERE job_type='appointment_reminder' "
            "AND payload_json LIKE ? ORDER BY id",
            (f'%\"appointment_id\": {appointment_id}%',),
        ).fetchall()
    assert [row["status"] for row in reminders] == ["running"]


def test_prepare_reschedule_serializes_running_reminder_check(app_bundle, monkeypatch):
    app, _, _ = app_bundle
    appointment_id = _book_calendar_appointment(app)
    store = app.extensions["store"]
    service = app.extensions["scheduling"]
    store.schedule_job(
        "default", "appointment_reminder", f"test-reminder:{appointment_id}",
        "2099-01-01T00:00:00+00:00", {"appointment_id": appointment_id},
    )
    target_start = datetime.now(ZoneInfo("Europe/Amsterdam")).replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=7)
    reminder_check_entered = threading.Event()
    allow_reminder_check_to_finish = threading.Event()
    prepare_started = threading.Event()
    prepare_errors = []
    original_check = store._appointment_has_running_reminder

    def pause_after_reminder_check(db, workspace_id, checked_appointment_id):
        running = original_check(db, workspace_id, checked_appointment_id)
        reminder_check_entered.set()
        if not allow_reminder_check_to_finish.wait(timeout=5):
            raise TimeoutError("test did not release the reminder check")
        return running

    monkeypatch.setattr(
        type(store), "_appointment_has_running_reminder", staticmethod(pause_after_reminder_check),
    )

    def prepare():
        prepare_started.set()
        try:
            service.prepare_reschedule(appointment_id, target_start.isoformat())
        except Exception as exc:  # Captured across the worker thread for deterministic assertions below.
            prepare_errors.append(exc)

    prepare_thread = threading.Thread(target=prepare, daemon=True)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "UPDATE background_jobs SET status='running' WHERE job_type='appointment_reminder' "
            "AND payload_json LIKE ?",
            (f'%\"appointment_id\": {appointment_id}%',),
        )
        prepare_thread.start()
        prepare_started_in_time = prepare_started.wait(timeout=5)
        check_raced_ahead_of_writer_lock = reminder_check_entered.wait(timeout=0.5)

    allow_reminder_check_to_finish.set()
    prepare_thread.join(timeout=5)

    assert not prepare_thread.is_alive()
    assert prepare_started_in_time
    assert not check_raced_ahead_of_writer_lock
    assert len(prepare_errors) == 1 and isinstance(prepare_errors[0], ValueError)
    assert store.get_appointment("default", appointment_id)["status"] == "booked"


def test_reschedule_browser_review_requires_csrf_and_explicit_confirmation(app_bundle):
    app, calendar, _ = app_bundle
    appointment_id = _book_calendar_appointment(app)
    store = app.extensions["store"]
    target_start = datetime.now(ZoneInfo("Europe/Amsterdam")).replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=6)
    client = app.test_client()
    with client.session_transaction() as session:
        session["operator_authenticated"] = True
        session["csrf_token"] = "reschedule-csrf"

    rejected = client.post(
        f"/actions/appointments/{appointment_id}/reschedule",
        data={"start_at": target_start.replace(tzinfo=None).isoformat()},
    )
    assert rejected.status_code == 403
    assert store.get_appointment("default", appointment_id)["status"] == "booked"

    prepared = client.post(
        f"/actions/appointments/{appointment_id}/reschedule",
        data={"csrf_token": "reschedule-csrf", "start_at": target_start.replace(tzinfo=None).isoformat()},
    )
    assert prepared.status_code == 302
    assert store.get_appointment("default", appointment_id)["status"] == "reschedule_pending"
    review = client.get("/?request=1")
    assert b"Review time change" in review.data
    assert b"Confirm and update Google Calendar" in review.data
    assert calendar.updated == []

    confirmed = client.post(
        f"/actions/appointments/{appointment_id}/reschedule/confirm",
        data={"csrf_token": "reschedule-csrf"},
    )
    assert confirmed.status_code == 302
    assert store.get_appointment("default", appointment_id)["status"] == "booked"
    assert calendar.updated == [f"event-{appointment_id}"]


def test_reschedule_rejects_busy_slot_without_changing_booking(app_bundle):
    app, calendar, _ = app_bundle
    appointment_id = _book_calendar_appointment(app)
    store = app.extensions["store"]
    original_start = store.get_appointment("default", appointment_id)["start_at"]
    calendar.slot_available = False
    target_start = datetime.now(ZoneInfo("Europe/Amsterdam")).replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=3)

    with pytest.raises(CalendarUnavailable, match="no longer available"):
        app.extensions["scheduling"].prepare_reschedule(appointment_id, target_start.isoformat())

    appointment = store.get_appointment("default", appointment_id)
    assert appointment["status"] == "booked"
    assert appointment["start_at"] == original_start
    assert appointment["pending_start_at"] is None


def test_reschedule_rechecks_availability_at_confirmation(app_bundle):
    app, calendar, _ = app_bundle
    appointment_id = _book_calendar_appointment(app)
    store = app.extensions["store"]
    target_start = datetime.now(ZoneInfo("Europe/Amsterdam")).replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=3)
    service = app.extensions["scheduling"]
    service.prepare_reschedule(appointment_id, target_start.isoformat())
    calendar.slot_available = False

    with pytest.raises(CalendarUnavailable, match="no longer available"):
        service.confirm_reschedule(appointment_id)

    appointment = store.get_appointment("default", appointment_id)
    assert appointment["status"] == "reschedule_pending"
    assert appointment["start_at"] != target_start.isoformat()
    assert calendar.updated == []


def test_reschedule_timeout_is_read_only_reconciled_when_calendar_already_moved(app_bundle):
    app, calendar, _ = app_bundle
    appointment_id = _book_calendar_appointment(app)
    store = app.extensions["store"]
    target_start = datetime.now(ZoneInfo("Europe/Amsterdam")).replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=4)
    service = app.extensions["scheduling"]
    service.prepare_reschedule(appointment_id, target_start.isoformat())
    update = calendar.update_event

    def update_then_timeout(*args):
        update(*args)
        raise TimeoutError("synthetic lost update response")

    calendar.update_event = update_then_timeout
    with pytest.raises(CalendarUnavailable, match="(?i)verify its state"):
        service.confirm_reschedule(appointment_id)
    assert store.get_appointment("default", appointment_id)["status"] == "reschedule_manual_required"
    assert store.get_appointment("default", appointment_id)["start_at"] != target_start.isoformat()

    reconciled = service.reconcile_reschedule(appointment_id)

    assert reconciled["status"] == "booked"
    assert store.get_appointment("default", appointment_id)["start_at"] == target_start.isoformat()


def test_reschedule_timeout_before_provider_update_restores_existing_booking(app_bundle):
    app, calendar, _ = app_bundle
    appointment_id = _book_calendar_appointment(app)
    store = app.extensions["store"]
    original_start = store.get_appointment("default", appointment_id)["start_at"]
    target_start = datetime.now(ZoneInfo("Europe/Amsterdam")).replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=5)
    service = app.extensions["scheduling"]
    service.prepare_reschedule(appointment_id, target_start.isoformat())
    calendar.update_event = lambda *_args: (_ for _ in ()).throw(TimeoutError("synthetic timeout before update"))

    with pytest.raises(CalendarUnavailable):
        service.confirm_reschedule(appointment_id)
    assert store.get_appointment("default", appointment_id)["status"] == "reschedule_manual_required"

    reconciled = service.reconcile_reschedule(appointment_id)

    assert reconciled["status"] == "unchanged"
    assert store.get_appointment("default", appointment_id)["start_at"] == original_start
    assert store.get_appointment("default", appointment_id)["pending_start_at"] is None


def test_worker_recovers_stale_reschedule_for_manual_verification(app_bundle):
    app, calendar, _ = app_bundle
    appointment_id = _book_calendar_appointment(app)
    store = app.extensions["store"]
    target_start = datetime.now(ZoneInfo("Europe/Amsterdam")).replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=8)
    service = app.extensions["scheduling"]
    service.prepare_reschedule(appointment_id, target_start.isoformat())
    assert store.claim_reschedule("default", appointment_id, "operator") is not None
    with store.connect() as db:
        db.execute("UPDATE appointments SET updated_at='2000-01-01T00:00:00+00:00' WHERE id=?", (appointment_id,))

    result = service.run_due_jobs()

    assert result["recovered_reschedules"] == 1
    assert store.get_appointment("default", appointment_id)["status"] == "reschedule_manual_required"
    assert calendar.updated == []
    assert service.reconcile_reschedule(appointment_id)["status"] == "unchanged"


def test_booking_cannot_be_cancelled_midflight_and_completion_is_atomic(app_bundle, auth_headers):
    app, _, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    post_webhook(client, webhook("wamid.2", body="The second one works for me"))
    appointment_id = store.dashboard("default")["items"][0]["appointment_id"]

    assert store.claim_booking("default", appointment_id, "test_operator") is not None
    appointment = store.get_appointment("default", appointment_id)
    assert appointment["status"] == "booking"
    assert store.request_detail("default", appointment["request_id"])["status"] == "booking_pending"

    cancelled = client.post(f"/api/appointments/{appointment_id}/cancel", headers=auth_headers)
    assert cancelled.status_code == 409
    assert store.get_appointment("default", appointment_id)["status"] == "booking"

    with store.connect() as db:
        db.execute(
            "CREATE TRIGGER fail_transition_audit BEFORE INSERT ON audit_events "
            "WHEN NEW.action='request.transition' BEGIN SELECT RAISE(ABORT,'injected audit failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected audit failure"):
        store.mark_booked("default", appointment_id, "google-event-1", "https://calendar.example/event")

    assert store.get_appointment("default", appointment_id)["status"] == "booking"
    assert store.get_appointment("default", appointment_id)["google_event_id"] is None
    assert store.request_detail("default", appointment["request_id"])["status"] == "booking_pending"

    with store.connect() as db:
        db.execute("DROP TRIGGER fail_transition_audit")
    store.mark_booked("default", appointment_id, "google-event-1", "https://calendar.example/event")
    assert store.get_appointment("default", appointment_id)["status"] == "booked"
    assert store.request_detail("default", appointment["request_id"])["status"] == "booked"


def test_public_booking_link_expires(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    proposal = store.get_proposal("default", item["proposal_id"])
    with store.connect() as db:
        db.execute("UPDATE proposals SET created_at='2020-01-01T00:00:00+00:00' WHERE id=?", (item["proposal_id"],))
    assert client.get(f"/book/{proposal['booking_token']}").status_code == 200
    with store.connect() as db:
        db.execute("UPDATE proposals SET sent_at='2020-01-01T00:00:00+00:00' WHERE id=?", (item["proposal_id"],))
    response = client.get(f"/book/{proposal['booking_token']}")
    assert response.status_code == 410
    assert b"booking link has expired" in response.data


def test_cancel_is_idempotent_and_calls_calendar(app_bundle, auth_headers):
    app, calendar, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    item = app.extensions["store"].dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    post_webhook(client, webhook("wamid.2", body="1"))
    item = app.extensions["store"].dashboard("default")["items"][0]
    app.extensions["scheduling"].book_appointment(item["appointment_id"])
    result = client.post(f"/api/appointments/{item['appointment_id']}/cancel", headers=auth_headers)
    assert result.status_code == 200 and result.get_json()["changed"] is True
    assert calendar.cancelled == [f"event-{item['appointment_id']}"]
