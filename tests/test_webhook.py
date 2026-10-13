
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


def test_signed_status_webhooks_store_latest_provider_receipt_idempotently(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    app.extensions["scheduling"].process_payload(webhook())
    proposal = app.extensions["store"].dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(proposal["proposal_id"])

    def status_event(status, timestamp, **extra):
        return {
            "entry": [{"changes": [{"value": {
                "metadata": {"phone_number_id": "123"},
                "statuses": [{
                    "id": "wamid.out.1", "status": status, "timestamp": str(timestamp),
                    "recipient_id": "31612345678", **extra,
                }],
            }}]}]
        }

    delivered = post_webhook(client, status_event("delivered", 1786000010))
    duplicate = post_webhook(client, status_event("delivered", 1786000010))
    read = post_webhook(client, status_event("read", 1786000020))
    late_delivery = post_webhook(client, status_event("delivered", 1786000010))

    assert delivered.get_json()["delivery_statuses"] == 1
    assert duplicate.get_json()["duplicate_statuses"] == 1
    assert read.get_json()["delivery_statuses"] == 1
    assert late_delivery.get_json()["duplicate_statuses"] == 1
    detail = app.extensions["store"].request_detail("default", proposal["id"])
    assert detail["delivery_status"] == {
        "status": "read", "provider_timestamp": "2026-08-06T07:07:00+00:00", "error_code": None,
    }
    with client.session_transaction() as current:
        current["operator_authenticated"] = True
        current["csrf_token"] = "webhook-status-test"
    page = client.get(f"/?view=scheduling&request={proposal['id']}")
    assert b"WhatsApp delivery status" in page.data
    assert b"read" in page.data
    assert b"31612345678" not in page.data
    with app.extensions["store"].connect() as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(whatsapp_delivery_events)")}
        rows = db.execute("SELECT * FROM whatsapp_delivery_events").fetchall()
        audit_count = db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action='whatsapp.delivery_status'",
        ).fetchone()[0]
    assert len(rows) == 2
    assert audit_count == 2
    assert "recipient_id" not in columns
    assert "raw_payload" not in columns


def test_status_receipts_are_phone_scoped_and_invalid_statuses_are_ignored(app_bundle):
    app, _, _ = app_bundle

    def payload(status, phone_number_id="123"):
        return {"entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": phone_number_id},
            "statuses": [{"id": "wamid.unknown", "status": status, "timestamp": "1786000010"}],
        }}]}]}

    client = app.test_client()
    wrong_number = post_webhook(client, payload("delivered", "another-number"))
    invalid_status = post_webhook(client, payload("sent-but-unknown"))
    # A malformed timestamp cannot produce a trusted ordering key.
    invalid_timestamp_payload = payload("read")
    invalid_timestamp_payload["entry"][0]["changes"][0]["value"]["statuses"][0]["timestamp"] = "not-a-time"
    invalid_timestamp = post_webhook(client, invalid_timestamp_payload)

    assert wrong_number.get_json()["ignored"] == 1
    assert invalid_status.get_json()["ignored"] == 1
    assert invalid_timestamp.get_json()["ignored"] == 1
    with app.extensions["store"].connect() as db:
        assert db.execute("SELECT COUNT(*) FROM whatsapp_delivery_events").fetchone()[0] == 0


def test_failed_status_retains_only_the_bounded_provider_error_code(app_bundle):
    app, _, _ = app_bundle
    payload = {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "123"},
        "statuses": [{
            "id": "wamid.failed", "status": "failed", "timestamp": "1786000010",
            "recipient_id": "31612345678",
            "errors": [{"code": 131014, "title": "Provider failure", "message": "private provider details"}],
        }],
    }}]}]}

    response = post_webhook(app.test_client(), payload)

    assert response.get_json()["delivery_statuses"] == 1
    with app.extensions["store"].connect() as db:
        event = db.execute("SELECT * FROM whatsapp_delivery_events").fetchone()
        audit = db.execute("SELECT detail_json FROM audit_events WHERE action='whatsapp.delivery_status'").fetchone()
    assert event["error_code"] == "131014"
    assert "private provider details" not in str(dict(event))
    assert "private provider details" not in audit[0]


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
