import pytest

from scheduler.app import create_app

from .conftest import post_webhook, webhook


def test_production_configuration_fails_closed(tmp_path):
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        create_app({"app_env": "production", "database_path": tmp_path / "db.sqlite", "public_base_url": "http://localhost"})


def test_api_requires_authentication(app_bundle):
    app, _, _ = app_bundle
    response = app.test_client().get("/api/requests")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "authentication_required"


def test_browser_login_and_csrf(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    client.get("/login")
    with client.session_transaction() as current:
        csrf = current["csrf_token"]
    assert client.post("/login", data={"csrf_token": csrf, "password": "wrong"}).status_code == 302
    assert client.post("/login", data={"csrf_token": csrf, "password": "correct horse battery staple"}).status_code == 302
    assert client.get("/").status_code == 200
    assert client.post("/actions/automation/toggle").status_code == 403


def test_browser_login_throttles_repeated_failures(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    client.get("/login")
    with client.session_transaction() as current:
        csrf = current["csrf_token"]
    for _ in range(5):
        assert client.post("/login", data={"csrf_token": csrf, "password": "wrong"}).status_code == 302
    throttled = client.post("/login", data={"csrf_token": csrf, "password": "correct horse battery staple"})
    assert throttled.status_code == 429
    assert b"Too many failed sign-in attempts" in throttled.data


def test_revoked_consent_blocks_proposal_send(app_bundle):
    app, _, whatsapp = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    contact = store.contacts("default")[0]
    store.update_contact(
        "default", contact["id"], display_name=contact["display_name"], email=contact["email"],
        timezone_name=contact["timezone"], language=contact["language"], consent_status="revoked",
    )
    with pytest.raises(ValueError, match="consent is revoked"):
        app.extensions["scheduling"].send_proposal(item["proposal_id"])
    assert whatsapp.sent == []


def test_csv_export_is_not_limited_to_dashboard_page(app_bundle, auth_headers):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    contact_id = store.upsert_contact("default", "31600000000", "Europe/Amsterdam")
    now = "2026-08-08T00:00:00+00:00"
    with store.connect() as db:
        db.executemany(
            "INSERT INTO scheduling_requests(workspace_id,contact_id,source_message_id,title,duration_minutes,timezone,requested_start,status,confidence,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [("default", contact_id, f"source-{index}", f"Call {index}", 30, "Europe/Amsterdam", None, "proposal_pending", 0.9, now, now) for index in range(125)],
        )
    response = app.test_client().get("/api/export/requests.csv", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.data.decode().splitlines()) == 126


def test_contact_export_delete_and_workspace_isolation(app_bundle, auth_headers):
    app, _, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    contact = store.contacts("default")[0]
    exported = client.get(f"/api/contacts/{contact['id']}/export", headers=auth_headers)
    assert exported.status_code == 200
    assert exported.get_json()["messages"][0]["body"].startswith("Could we")
    assert store.dashboard("other-workspace")["total"] == 0
    deleted = client.delete(f"/api/contacts/{contact['id']}", headers=auth_headers)
    assert deleted.get_json()["deleted"] is True
    assert store.contacts("default") == []


def test_sensitive_message_is_encrypted_in_database(app_bundle):
    app, _, _ = app_bundle
    post_webhook(app.test_client(), webhook(body="Private scheduling sentence"))
    store = app.extensions["store"]
    with store.connect() as db:
        raw = db.execute("SELECT body_ciphertext FROM inbound_messages").fetchone()[0]
    assert raw.startswith("enc:")
    assert "Private scheduling sentence" not in raw
