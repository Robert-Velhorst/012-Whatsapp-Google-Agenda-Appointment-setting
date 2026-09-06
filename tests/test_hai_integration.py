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
        "hai_allowed_networks": "127.0.0.1/32", "hai_feed_page_size": 100,
    }, calendar=FakeCalendar(), whatsapp=FakeWhatsApp())
    app.config["TESTING"] = True
    client = app.test_client()
    post_webhook(client, webhook(body="Private message from Emma about a confidential appointment"))

    denied = client.get("/api/integrations/hai/feed", headers={"X-Forwarded-For": "203.0.113.10"})
    assert denied.status_code == 403
    first = client.get("/api/integrations/hai/feed")
    assert first.status_code == 200
    payload = first.get_json()
    assert len(payload["items"]) == 1 and payload["nextCursor"]
    serialized = first.get_data(as_text=True)
    assert "31612345678" not in serialized
    assert "Private message from Emma" not in serialized
    assert payload["items"][0]["itemType"] == "scheduling_request"
    assert "advisory_read_only" in payload["items"][0]["metadata"]
    second = client.get("/api/integrations/hai/feed", query_string={"cursor": payload["nextCursor"]})
    assert second.get_json()["items"] == []
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
