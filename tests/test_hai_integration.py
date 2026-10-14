import pytest

from .conftest import post_webhook, webhook


def test_hai_feed_is_disabled_by_default(app_bundle):
    app, _, _ = app_bundle
    assert app.test_client().get("/api/integrations/hai/feed").status_code == 404


def test_hai_feed_is_local_cursor_based_and_pii_minimized(tmp_path):
    from scheduler.app import create_app

    from .conftest import FakeCalendar, FakeWhatsApp

    app = create_app({
        "app_env": "test", "database_path": tmp_path / "hai.sqlite3", "flask_secret_key": "test-secret",
        "admin_api_token": "test-token", "data_encryption_key": "test-encryption", "whatsapp_app_secret": "test-app-secret",
        "whatsapp_access_token": "token", "whatsapp_phone_number_id": "123", "hai_connector_enabled": True,
        "hai_allowed_networks": "127.0.0.1/32", "hai_feed_page_size": 2,
    }, calendar=FakeCalendar(), whatsapp=FakeWhatsApp())
    app.config["TESTING"] = True
    client = app.test_client()
    post_webhook(client, webhook(body="Private message from Emma about a confidential appointment"))
    post_webhook(client, webhook(message_id="wamid.2", body="Could we schedule a second 30 minute call tomorrow?"))

    denied = client.get("/api/integrations/hai/feed", headers={"X-Forwarded-For": "203.0.113.10"})
    assert denied.status_code == 403
    spoofed_loopback = client.get("/api/integrations/hai/feed", headers={"X-Forwarded-For": "127.0.0.1"})
    assert spoofed_loopback.status_code == 403
    first = client.get("/api/integrations/hai/feed")
    assert first.status_code == 200
    payload = first.get_json()
    assert set(payload) == {"items", "nextCursor", "cursor"}
    assert len(payload["items"]) == 2 and payload["nextCursor"]
    assert payload["cursor"] == payload["nextCursor"]
    serialized = first.get_data(as_text=True)
    assert "31612345678" not in serialized
    assert "Private message from Emma" not in serialized
    assert [item["metadata"]["requestId"] for item in payload["items"]] == [1, 2]
    item = payload["items"][-1]
    assert {"externalId", "title", "content", "itemType", "provider", "receivedAt", "metadata"} <= set(item)
    assert item["itemType"] == "message"
    assert item["provider"] == "generic_json_feed"
    assert isinstance(item["metadata"], dict)
    assert item["metadata"]["authority"] == "advisory_read_only"
    assert item["metadata"]["requestId"] == 2
    # The initial snapshot is returned oldest-to-newest, so its cursor must
    # mark the newest item and an unchanged subsequent sync must not replay it.
    unchanged = client.get("/api/integrations/hai/feed", query_string={"cursor": payload["nextCursor"]})
    assert unchanged.status_code == 200
    assert unchanged.get_json()["items"] == []
    post_webhook(client, webhook(message_id="wamid.3", body="Could we schedule another 30 minute call next week?"))
    second = client.get("/api/integrations/hai/feed", query_string={"cursor": payload["nextCursor"]})
    second_payload = second.get_json()
    assert [item["metadata"]["requestId"] for item in second_payload["items"]] == [3]
    assert second_payload["nextCursor"] == second_payload["cursor"]
    app.extensions["store"].close()


def test_hai_feed_rejects_invalid_cursor(tmp_path):
    from scheduler.app import create_app

    from .conftest import FakeCalendar, FakeWhatsApp

    app = create_app({
        "app_env": "test", "database_path": tmp_path / "hai-invalid.sqlite3", "flask_secret_key": "test-secret",
        "admin_api_token": "test-token", "data_encryption_key": "test-encryption", "hai_connector_enabled": True,
        "hai_allowed_networks": "127.0.0.1/32",
    }, calendar=FakeCalendar(), whatsapp=FakeWhatsApp())
    response = app.test_client().get("/api/integrations/hai/feed?cursor=not-a-cursor")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_cursor"
    app.extensions["store"].close()


def test_hai_feed_does_not_return_exception_details_to_client(tmp_path, monkeypatch):
    from scheduler.app import create_app

    from .conftest import FakeCalendar, FakeWhatsApp

    app = create_app({
        "app_env": "test", "database_path": tmp_path / "hai-error.sqlite3", "flask_secret_key": "test-secret",
        "admin_api_token": "test-token", "data_encryption_key": "test-encryption", "hai_connector_enabled": True,
        "hai_allowed_networks": "127.0.0.1/32",
    }, calendar=FakeCalendar(), whatsapp=FakeWhatsApp())
    app.extensions["store"].hai_feed = lambda *_args: (_ for _ in ()).throw(
        ValueError("Traceback (most recent call last): /srv/private/database.py:42")
    )

    response = app.test_client().get("/api/integrations/hai/feed?cursor=malformed")

    assert response.status_code == 400
    assert response.get_json()["error"] == {
        "code": "invalid_cursor",
        "message": "The HAI feed cursor is invalid.",
        "retryable": False,
    }
    assert b"Traceback" not in response.data
    assert b"/srv/private" not in response.data
    app.extensions["store"].close()


@pytest.mark.parametrize("automation_paused", [True, False])
def test_public_ingress_allows_google_oauth_bootstrap_only_while_automation_is_paused(tmp_path, automation_paused):
    from scheduler.app import create_app

    from .conftest import FakeWhatsApp

    class DisconnectedCalendar:
        def connected(self):
            return False

    google_client = tmp_path / "google-client.json"
    google_client.write_text("{}", encoding="utf-8")
    app = create_app({
        "app_env": "production",
        "database_path": tmp_path / "ingress.sqlite3",
        "public_base_url": "https://agenda.example.ngrok.app",
        "flask_secret_key": "f" * 40,
        "admin_api_token": "a" * 40,
        "admin_password_hash": "configured-password-hash",
        "data_encryption_key": "e" * 64,
        "whatsapp_cloud_api_enabled": True,
        "whatsapp_verify_token": "v" * 32,
        "whatsapp_app_secret": "s" * 32,
        "whatsapp_access_token": "t" * 32,
        "whatsapp_phone_number_id": "123456789",
        "google_client_secrets_file": str(google_client),
        "automation_paused": automation_paused,
    }, calendar=DisconnectedCalendar(), whatsapp=FakeWhatsApp())

    readiness = app.extensions["scheduling"].readiness()
    assert readiness["ready"] is False  # OAuth is incomplete and automation is paused.
    assert readiness["providers"]["google_calendar"]["ready"] is False
    assert readiness["automation_paused"] is automation_paused
    assert readiness["public_ingress"]["ready"] is automation_paused
    if not automation_paused:
        assert "pause automation" in readiness["public_ingress"]["detail"]
    client = app.test_client()
    assert client.get("/api/operator/readiness").status_code == 401
    response = client.get("/api/operator/readiness", headers={"Authorization": "Bearer " + "a" * 40})
    assert response.status_code == 200
    assert response.get_json()["public_ingress"]["ready"] is automation_paused
    app.extensions["store"].close()
