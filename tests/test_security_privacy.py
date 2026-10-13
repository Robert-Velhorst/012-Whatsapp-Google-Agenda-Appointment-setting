import pytest

from scheduler.app import create_app

from .conftest import post_webhook, webhook


def test_production_configuration_fails_closed(tmp_path):
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        create_app({"app_env": "production", "database_path": tmp_path / "db.sqlite", "public_base_url": "http://localhost"})


def test_production_rejects_short_encryption_key(tmp_path):
    with pytest.raises(RuntimeError, match="DATA_ENCRYPTION_KEY must be at least 64 characters"):
        create_app({
            "app_env": "production",
            "database_path": tmp_path / "db.sqlite",
            "public_base_url": "https://agenda.example",
            "flask_secret_key": "f" * 64,
            "admin_api_token": "a" * 64,
            "admin_password_hash": "hash",
            "data_encryption_key": "short-passphrase",
            "whatsapp_verify_token": "v" * 64,
            "whatsapp_app_secret": "s" * 64,
            "whatsapp_access_token": "t" * 64,
            "whatsapp_phone_number_id": "123",
        })


def test_production_personal_assisted_mode_does_not_require_business_api(tmp_path):
    from .conftest import FakeCalendar, FakeWhatsApp

    google_client = tmp_path / "google-client.json"
    google_client.write_text("{}", encoding="utf-8")
    app = create_app({
        "app_env": "production",
        "database_path": tmp_path / "personal.sqlite3",
        "public_base_url": "https://agenda.example.ngrok.app",
        "flask_secret_key": "f" * 64,
        "admin_api_token": "a" * 64,
        "admin_password_hash": "configured-password-hash",
        "data_encryption_key": "e" * 64,
        "whatsapp_cloud_api_enabled": False,
        "google_client_secrets_file": str(google_client),
        "automation_paused": True,
    }, calendar=FakeCalendar(), whatsapp=FakeWhatsApp())

    readiness = app.extensions["scheduling"].readiness()
    assert readiness["providers"]["whatsapp"]["ready"] is True
    assert readiness["providers"]["whatsapp"]["enabled"] is False
    assert readiness["public_ingress"]["ready"] is True
    assert app.test_client().get("/webhook/whatsapp?hub.verify_token=x").status_code == 403
    app.extensions["store"].close()


def test_cloud_api_mode_preserves_existing_credential_installations(monkeypatch):
    from scheduler.config import Settings

    monkeypatch.delenv("WHATSAPP_CLOUD_API_ENABLED", raising=False)
    settings = Settings.from_env({
        "whatsapp_verify_token": "verify", "whatsapp_app_secret": "secret",
        "whatsapp_access_token": "token", "whatsapp_phone_number_id": "123",
    })
    assert settings.whatsapp_cloud_api_enabled is True

    monkeypatch.setenv("WHATSAPP_CLOUD_API_ENABLED", "false")
    settings = Settings.from_env({"whatsapp_access_token": "legacy-token"})
    assert settings.whatsapp_cloud_api_enabled is False


def test_api_requires_authentication(app_bundle):
    app, _, _ = app_bundle
    response = app.test_client().get("/api/requests")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "authentication_required"


def test_audit_api_clamps_negative_limit(app_bundle, auth_headers):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    for index in range(3):
        store.audit("default", "test", f"audit-{index}", "test")

    response = app.test_client().get("/api/audit?limit=-1", headers=auth_headers)

    assert response.status_code == 200
    assert len(response.get_json()) == 1


def test_requests_api_clamps_page_to_available_results(app_bundle, auth_headers):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    contact_id = store.upsert_contact("default", "31600000002", "Europe/Amsterdam")
    for index in range(3):
        store.create_request("default", contact_id, f"pagination-{index}", f"Request {index}", 30, "Europe/Amsterdam", "2026-10-13", 0.8)

    response = app.test_client().get("/api/requests?page=" + ("9" * 1000) + "&per_page=2", headers=auth_headers)

    assert response.status_code == 200
    assert response.get_json()["page"] == 2
    assert response.get_json()["total"] == 3
    assert len(response.get_json()["items"]) == 1


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


def test_automation_cannot_resume_before_providers_are_ready(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    app.extensions["calendar"].connected = lambda: False
    app.extensions["whatsapp"].configured = lambda: False
    app.extensions["store"].set_state("default", "automation_paused", "true", "test")
    with client.session_transaction() as current:
        current["operator_authenticated"] = True
        current["csrf_token"] = "valid-test-csrf"

    response = client.post("/actions/automation/toggle", data={"csrf_token": "valid-test-csrf"})

    assert response.status_code == 302
    assert app.extensions["scheduling"].is_paused() is True
    assert b"Automation cannot resume until setup issues are resolved" in client.get("/").data


def test_browser_login_rejects_external_next_redirect(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    client.get("/login")
    with client.session_transaction() as current:
        csrf = current["csrf_token"]
    response = client.post("/login?next=https://evil.example/steal", data={"csrf_token": csrf, "password": "correct horse battery staple"})
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


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


def test_csv_export_neutralizes_spreadsheet_formulas(app_bundle, auth_headers):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    contact_id = store.upsert_contact("default", "31600000001", "Europe/Amsterdam", display_name="=HYPERLINK(\"https://evil.example\")")
    store.create_request("default", contact_id, "csv-formula", "+CMD|' /C calc'!A0", 30, "Europe/Amsterdam", "2026-08-09", 0.8)
    csv_data = app.test_client().get("/api/export/requests.csv", headers=auth_headers).data.decode()
    assert "'=HYPERLINK" in csv_data
    assert "'+CMD" in csv_data


def test_contact_export_delete_and_workspace_isolation(app_bundle, auth_headers):
    app, _, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    contact = store.contacts("default")[0]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    post_webhook(client, webhook("wamid.2", body="1"))
    exported = client.get(f"/api/contacts/{contact['id']}/export", headers=auth_headers)
    assert exported.status_code == 200
    assert exported.headers["Content-Disposition"] == f'attachment; filename="contact-{contact["id"]}-export.json"'
    export_data = exported.get_json()
    assert export_data["messages"][0]["body"].startswith("Could we")
    assert len(export_data["proposals"]) == 1
    assert export_data["proposals"][0]["reply"]
    assert len(export_data["appointments"]) == 1
    assert "booking_token" not in str(export_data)
    assert "booking_token_hash" not in str(export_data)
    assert "booking_token_ciphertext" not in str(export_data)
    assert any(event["action"] == "privacy.contact_exported" for event in store.recent_audit("default", 10))
    assert store.dashboard("other-workspace")["total"] == 0
    assert client.post(f"/api/appointments/{export_data['appointments'][0]['id']}/cancel", headers=auth_headers).status_code == 200
    deleted = client.delete(f"/api/contacts/{contact['id']}", headers=auth_headers)
    assert deleted.get_json()["deleted"] is True
    assert store.contacts("default") == []


def test_contact_delete_refuses_unresolved_calendar_appointments(app_bundle, auth_headers):
    app, calendar, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    post_webhook(client, webhook("wamid.2", body="1"))
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].book_appointment(item["appointment_id"])

    deleted = client.delete(f"/api/contacts/{item['contact_id']}", headers=auth_headers)

    assert deleted.status_code == 409
    assert deleted.get_json()["error"]["code"] == "contact_has_unresolved_appointments"
    assert store.get_contact("default", item["contact_id"]) is not None
    assert store.get_appointment("default", item["appointment_id"])["status"] == "booked"
    assert calendar.cancelled == []

    cancelled = client.post(f"/api/appointments/{item['appointment_id']}/cancel", headers=auth_headers)
    assert cancelled.status_code == 200
    assert calendar.cancelled == [f"event-{item['appointment_id']}"]
    deleted = client.delete(f"/api/contacts/{item['contact_id']}", headers=auth_headers)
    assert deleted.status_code == 200
    assert deleted.get_json()["deleted"] is True
    assert store.get_contact("default", item["contact_id"]) is None


def test_browser_contact_delete_requires_csrf_and_recent_password(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    contact = app.extensions["store"].contacts("default")[0]
    with client.session_transaction() as current:
        current["operator_authenticated"] = True
        current["csrf_token"] = "valid-test-csrf"

    action = f"/actions/contacts/{contact['id']}/delete"
    assert client.post(action, data={"password": "correct horse battery staple"}).status_code == 403
    assert app.extensions["store"].get_contact("default", contact["id"]) is not None

    rejected = client.post(action, data={"csrf_token": "valid-test-csrf", "password": "wrong"})
    assert rejected.status_code == 302
    assert app.extensions["store"].get_contact("default", contact["id"]) is not None
    assert b"enter the current operator password" in client.get(rejected.headers["Location"]).data

    deleted = client.post(action, data={"csrf_token": "valid-test-csrf", "password": "correct horse battery staple"})
    assert deleted.status_code == 302
    assert app.extensions["store"].get_contact("default", contact["id"]) is None


def test_browser_contact_delete_keeps_contact_when_appointment_is_active(app_bundle):
    app, calendar, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    post_webhook(client, webhook("wamid.2", body="1"))
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].book_appointment(item["appointment_id"])
    with client.session_transaction() as current:
        current["operator_authenticated"] = True
        current["csrf_token"] = "valid-test-csrf"

    response = client.post(
        f"/actions/contacts/{item['contact_id']}/delete",
        data={"csrf_token": "valid-test-csrf", "password": "correct horse battery staple"},
    )

    assert response.status_code == 302
    assert store.get_contact("default", item["contact_id"]) is not None
    assert calendar.cancelled == []
    assert b"Cancel or manually resolve" in client.get(response.headers["Location"]).data


def test_browser_contact_delete_reauthentication_is_rate_limited_and_not_logged(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    contact_id = app.extensions["store"].upsert_contact("default", "31600000099", "Europe/Amsterdam")
    with client.session_transaction() as current:
        current["operator_authenticated"] = True
        current["csrf_token"] = "valid-test-csrf"
    action = f"/actions/contacts/{contact_id}/delete"

    for _ in range(5):
        response = client.post(action, data={"csrf_token": "valid-test-csrf", "password": "wrong-secret"})
        assert response.status_code == 302
    blocked = client.post(action, data={"csrf_token": "valid-test-csrf", "password": "correct horse battery staple"})

    assert blocked.status_code == 302
    assert app.extensions["store"].get_contact("default", contact_id) is not None
    events = app.extensions["store"].recent_audit("default", 50)
    assert any(event["action"] == "auth.contact_delete_throttled" for event in events)
    assert all("wrong-secret" not in str(event["detail"]) for event in events)


def test_sensitive_message_is_encrypted_in_database(app_bundle):
    app, _, _ = app_bundle
    post_webhook(app.test_client(), webhook(body="Private scheduling sentence"))
    store = app.extensions["store"]
    with store.connect() as db:
        raw = db.execute("SELECT body_ciphertext FROM inbound_messages").fetchone()[0]
    assert raw.startswith("enc:")
    assert "Private scheduling sentence" not in raw

