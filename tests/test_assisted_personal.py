from __future__ import annotations

from datetime import date, time


def signed_in_client(app):
    client = app.test_client()
    with client.session_transaction() as current:
        current["operator_authenticated"] = True
        current["csrf_token"] = "assisted-test-csrf"
    return client


def test_assisted_analysis_stores_structured_request_but_not_pasted_text(app_bundle):
    app, calendar, whatsapp = app_bundle
    client = signed_in_client(app)

    response = client.post("/actions/assisted/analyze", data={
        "csrf_token": "assisted-test-csrf",
        "message": "Could we schedule a 45 minute call next Tuesday at 3?",
    })

    assert response.status_code == 302
    page = client.get(response.headers["Location"])
    assert b"Review suggested times" in page.data
    assert b"45 minutes" in page.data
    assert b"Open WhatsApp with this draft" in page.data
    assert b"not retained" in page.data
    assert calendar.preferred_times[-1] == time(15)
    store = app.extensions["store"]
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM inbound_messages").fetchone()[0] == 0
        request_row = db.execute("SELECT source_message_id FROM scheduling_requests").fetchone()
    assert request_row["source_message_id"].startswith("assisted:")
    assert whatsapp.sent == []


def test_assisted_analysis_passes_dutch_clock_time_and_default_duration_to_calendar(app_bundle):
    app, calendar, _ = app_bundle
    client = signed_in_client(app)

    response = client.post("/actions/assisted/analyze", data={
        "csrf_token": "assisted-test-csrf",
        "message": "Kunnen we dinsdagmiddag om 2 uur afspreken?",
    })

    assert response.status_code == 302
    assert calendar.preferred_times[-1] == time(14)
    with app.extensions["store"].connect() as db:
        request_row = db.execute("SELECT duration_minutes FROM scheduling_requests").fetchone()
    assert request_row["duration_minutes"] == app.extensions["settings"].default_duration_minutes


def test_assisted_proposal_requires_operator_confirmation_before_booking_link_works(app_bundle):
    app, calendar, whatsapp = app_bundle
    client = signed_in_client(app)
    response = client.post("/actions/assisted/analyze", data={
        "csrf_token": "assisted-test-csrf",
        "message": "Can we schedule a 30 minute meeting next week?",
    })
    proposal_id = int(response.headers["Location"].split("proposal=")[1])
    proposal = app.extensions["store"].get_proposal("default", proposal_id)
    token = proposal["booking_token"]
    requested_start = date.fromisoformat(proposal["requested_start"])
    assert all(date.fromisoformat(slot[:10]) >= requested_start for slot in proposal["slots"])
    assert "Reply with 1" not in proposal["reply_text"]
    assert "choose a time on this booking page" in proposal["reply_text"]

    assert client.get(f"/book/{token}").status_code == 404
    assert client.post(
        f"/actions/assisted/{proposal_id}/shared",
        data={"csrf_token": "assisted-test-csrf"},
    ).status_code == 302
    assert client.get(f"/book/{token}").status_code == 200
    assert whatsapp.sent == []

    confirmed = client.post(f"/book/{token}", data={"csrf_token": "assisted-test-csrf", "slot": "0", "consent": "yes"})
    assert confirmed.status_code == 200
    assert b"operator" in confirmed.data.lower()
    assert calendar.created == []
    assert whatsapp.sent == []


def test_assisted_booking_never_sends_personal_confirmation_or_queues_reminder(app_bundle):
    app, calendar, whatsapp = app_bundle
    service = app.extensions["scheduling"]
    store = app.extensions["store"]
    proposal_id = service.create_assisted_proposal("Please schedule a 30 minute call next week")
    store.mark_assisted_proposal_shared("default", proposal_id, "operator")
    appointment_id = store.confirm_proposal("default", proposal_id, 0, "contact")
    service._send_booking_confirmation = lambda _appointment: (_ for _ in ()).throw(
        AssertionError("personal WhatsApp must not enter the automatic confirmation path")
    )

    result = service.book_appointment(appointment_id)

    assert result["status"] == "booked"
    assert result["warning"] == "Appointment booked in Google Calendar. Send the WhatsApp confirmation draft manually."
    assert len(calendar.created) == 1
    assert calendar.created[0]["sender"].startswith("assisted:")
    assert whatsapp.sent == []
    assert store.dashboard("default")["jobs"] == []
    audit = store.recent_audit("default")
    assert any(
        item["action"] == "confirmation.manual_required"
        and item["detail"] == {"automatic_send": False, "channel": "personal_whatsapp"}
        for item in audit
    )
    assert not any(item["action"] == "confirmation.send_failed" for item in audit)


def test_assisted_proposal_cannot_be_sent_through_business_api(app_bundle):
    app, _, whatsapp = app_bundle
    proposal_id = app.extensions["scheduling"].create_assisted_proposal("Schedule a 30 minute call next week")

    try:
        app.extensions["scheduling"].send_proposal(proposal_id)
        assert False, "assisted proposals must not use the Business API"
    except ValueError as exc:
        assert "manual-only" in str(exc)
    assert whatsapp.sent == []


def test_booked_assisted_request_has_reviewable_personal_confirmation_draft(app_bundle):
    app, _, whatsapp = app_bundle
    service = app.extensions["scheduling"]
    store = app.extensions["store"]
    proposal_id = service.create_assisted_proposal("Plan a 30 minute call next week")
    proposal = store.get_proposal("default", proposal_id)
    store.mark_assisted_proposal_shared("default", proposal_id, "operator")
    appointment_id = store.confirm_proposal("default", proposal_id, 0, "contact")
    service.book_appointment(appointment_id)
    client = signed_in_client(app)

    page = client.get(f"/?view=scheduling&request={proposal['request_id']}")

    assert page.status_code == 200
    assert b"Personal WhatsApp confirmation draft" in page.data
    assert b"Open WhatsApp with confirmation" in page.data
    assert b'id="personal-confirmation-draft"' in page.data
    assert b'name="personal_confirmation_draft"' in page.data
    assert b'aria-labelledby="personal-confirmation-heading"' in page.data
    assert b"Not sent or delivery-verified" in page.data
    assert whatsapp.sent == []


def test_assisted_path_rejects_non_scheduling_and_missing_calendar_without_creating_records(app_bundle):
    app, _, _ = app_bundle
    client = signed_in_client(app)
    response = client.post("/actions/assisted/analyze", data={
        "csrf_token": "assisted-test-csrf", "message": "Thanks, see you later",
    })
    assert response.status_code == 302
    assert b"could not identify a scheduling request" in client.get(response.headers["Location"]).data
    assert app.extensions["store"].dashboard("default")["total"] == 0

    app.extensions["calendar"].connected = lambda: False
    response = client.post("/actions/assisted/analyze", data={
        "csrf_token": "assisted-test-csrf", "message": "Schedule a call next week",
    })
    assert response.status_code == 302
    assert b"Google Calendar is not connected" in client.get(response.headers["Location"]).data
    assert app.extensions["store"].dashboard("default")["total"] == 0


def test_assisted_calendar_failure_is_recorded_without_leaking_provider_details(app_bundle, monkeypatch):
    app, calendar, _ = app_bundle
    client = signed_in_client(app)
    secret_provider_detail = "PRIVATE_CALENDAR_PROVIDER_SECRET"

    def fail_free_slots(*args, **kwargs):
        raise RuntimeError(secret_provider_detail)

    monkeypatch.setattr(calendar, "free_slots", fail_free_slots)
    response = client.post(
        "/actions/assisted/analyze",
        data={
            "csrf_token": "assisted-test-csrf",
            "message": "Schedule a 30 minute meeting next week",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert secret_provider_detail.encode() not in response.data
    store = app.extensions["store"]
    with store.connect() as db:
        request_row = db.execute("SELECT id,status FROM scheduling_requests").fetchone()
    assert request_row["status"] == "failed"
    failed_transition = next(
        event for event in store.recent_audit("default")
        if event["action"] == "request.transition" and event["detail"].get("to") == "failed"
    )
    assert failed_transition["detail"]["error_class"] == "RuntimeError"
    assert "error" not in failed_transition["detail"]


def test_assisted_posts_require_operator_session_and_csrf(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    assert client.get("/?view=assisted").status_code == 302
    assert client.post("/actions/assisted/analyze", data={"message": "Schedule a meeting"}).status_code == 302
    client = signed_in_client(app)
    assert client.post("/actions/assisted/analyze", data={"message": "Schedule a meeting"}).status_code == 403
