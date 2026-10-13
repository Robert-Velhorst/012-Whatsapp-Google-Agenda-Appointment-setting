
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from .conftest import post_webhook, signed, webhook


def test_health_webhook_verification_and_security_headers(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    health = client.get("/api/health")
    assert health.status_code == 200 and health.get_json()["ok"]
    assert health.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in health.headers["Content-Security-Policy"]
    assert client.get("/webhook/whatsapp?hub.verify_token=verify-me&hub.challenge=ok").data == b"ok"
    assert client.get("/webhook/whatsapp?hub.verify_token=wrong&hub.challenge=ok").status_code == 403


def test_bad_signature_is_rejected(app_bundle):
    app, _, _ = app_bundle
    assert app.test_client().post("/webhook/whatsapp", json={}).status_code == 403


@pytest.mark.parametrize("payload", [
    [1],
    {"entry": [1]},
    {"entry": [{"changes": 1}]},
    {"entry": [{"changes": [{"value": None}]}]},
    {"entry": [{"changes": [{"value": {"messages": {"not": "a list"}}}]}]},
    {"entry": [{"changes": [{"value": {
        "metadata": None,
        "messages": [{"id": "wamid.no-metadata", "from": "31612345678", "type": "text", "text": {"body": "Book a call"}}],
    }}]}]},
])
def test_signed_malformed_payload_shapes_are_acknowledged_and_ignored(app_bundle, payload):
    app, _, _ = app_bundle

    response = post_webhook(app.test_client(), payload)

    assert response.status_code == 200
    assert response.get_json()["ignored"] == 1


@pytest.mark.parametrize("message", [
    1,
    {"id": "wamid.bad-text", "from": "31612345678", "type": "text", "text": None},
    {"id": "wamid.bad-body", "from": "31612345678", "type": "text", "text": {"body": 7}},
    {"id": 7, "from": "31612345678", "type": "text", "text": {"body": "Book a call"}},
    {"id": "wamid.bad-sender", "from": 7, "type": "text", "text": {"body": "Book a call"}},
])
def test_signed_malformed_messages_are_ignored(app_bundle, message):
    app, _, _ = app_bundle
    payload = webhook()
    payload["entry"][0]["changes"][0]["value"]["messages"] = [message]

    response = post_webhook(app.test_client(), payload)

    assert response.status_code == 200
    assert response.get_json()["ignored"] == 1


def test_malformed_optional_contacts_do_not_drop_a_valid_message(app_bundle):
    app, _, _ = app_bundle
    payload = webhook()
    payload["entry"][0]["changes"][0]["value"]["contacts"] = [1]

    response = post_webhook(app.test_client(), payload)

    assert response.status_code == 200
    assert response.get_json()["accepted"] == 1
    assert response.get_json()["proposals"] == 1


def test_out_of_range_timestamp_uses_safe_fallback(app_bundle):
    app, _, _ = app_bundle
    payload = webhook()
    payload["entry"][0]["changes"][0]["value"]["messages"][0]["timestamp"] = "999999999999999999999999999999999999"

    response = post_webhook(app.test_client(), payload)

    assert response.status_code == 200
    assert response.get_json()["accepted"] == 1


def test_webhook_is_idempotent_and_creates_reviewable_proposal(app_bundle, auth_headers):
    app, _, whatsapp = app_bundle
    client = app.test_client()
    first = post_webhook(client, webhook())
    duplicate = post_webhook(client, webhook())
    assert first.status_code == 200 and first.get_json()["proposals"] == 1
    assert duplicate.get_json()["duplicates"] == 1
    requests = client.get("/api/requests", headers=auth_headers).get_json()
    assert requests["total"] == 1
    assert requests["items"][0]["status"] == "proposal_pending"
    assert requests["items"][0]["proposal_status"] == "pending_approval"
    assert whatsapp.sent == []


def test_unrelated_followup_does_not_reuse_old_scheduling_intent(app_bundle, auth_headers):
    app, _, _ = app_bundle
    client = app.test_client()

    first = post_webhook(client, webhook())
    followup = post_webhook(client, webhook(message_id="wamid.thanks", body="Thanks!"))

    assert first.get_json()["proposals"] == 1
    assert followup.get_json()["proposals"] == 0
    assert followup.get_json()["ignored"] == 1
    assert client.get("/api/requests", headers=auth_headers).get_json()["total"] == 1

    new_request = post_webhook(
        client, webhook(message_id="wamid.second-request", body="Could we schedule another call next week?")
    )
    assert new_request.get_json()["proposals"] == 1
    assert client.get("/api/requests", headers=auth_headers).get_json()["total"] == 2


def test_new_request_does_not_inherit_an_old_message_date(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()

    post_webhook(client, webhook(body="Could we schedule a 30 minute call on 25/10/2026?"))
    post_webhook(client, webhook(message_id="wamid.new-date", body="Could we schedule another call?"))

    items = app.extensions["store"].dashboard("default")["items"]
    expected_date = datetime.now(ZoneInfo("Europe/Amsterdam")).date().isoformat()
    assert items[0]["requested_start"] == expected_date


def test_webhook_does_not_propose_calendar_slots_before_requested_start(app_bundle):
    app, calendar, whatsapp = app_bundle
    zone = ZoneInfo("Europe/Amsterdam")
    today = datetime.now(zone).date()
    requested_start = app.extensions["scheduling"].intent_provider.analyse(
        "Schedule a 30 minute call next week", today, 30
    ).requested_start
    calendar.free_slots = lambda *_args: [
        datetime.combine(requested_start - timedelta(days=1), time(10), tzinfo=zone)
    ]

    response = post_webhook(
        app.test_client(),
        webhook(body="Schedule a 30 minute call next week"),
    )

    assert response.get_json()["proposals"] == 0
    assert whatsapp.sent == []
    assert app.extensions["store"].dashboard("default")["items"][0]["status"] == "needs_clarification"


def test_webhook_ignores_messages_for_another_phone_number(app_bundle, auth_headers):
    app, _, whatsapp = app_bundle
    payload = webhook()
    payload["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = "another-number"

    response = post_webhook(app.test_client(), payload)

    assert response.status_code == 200
    assert response.get_json()["ignored"] == 1
    assert app.test_client().get("/api/requests", headers=auth_headers).get_json()["total"] == 0
    assert whatsapp.sent == []


def test_pause_records_message_but_stops_processing(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    store.set_state("default", "automation_paused", "true")
    response = post_webhook(app.test_client(), webhook())
    assert response.get_json()["accepted"] == 1
    assert app.extensions["store"].dashboard("default")["total"] == 0


def test_payload_size_is_limited(app_bundle):
    app, _, _ = app_bundle
    raw = b"x" * 1_000_100
    response = app.test_client().post("/webhook/whatsapp", data=raw, headers={"X-Hub-Signature-256": signed(raw)})
    assert response.status_code == 413
