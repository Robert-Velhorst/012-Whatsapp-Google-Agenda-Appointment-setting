import json

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
