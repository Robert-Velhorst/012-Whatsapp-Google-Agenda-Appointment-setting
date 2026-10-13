def test_favicon_is_linked_and_served(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()

    page = client.get("/login")
    assert page.status_code == 200
    assert b'rel="icon" type="image/svg+xml"' in page.data
    assert b"/static/favicon.svg" in page.data

    icon = client.get("/static/favicon.svg")
    assert icon.status_code == 200
    assert icon.mimetype == "image/svg+xml"
    assert b"<svg" in icon.data


def test_personal_whatsapp_assisted_screen_is_in_operator_navigation(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    with client.session_transaction() as current:
        current["operator_authenticated"] = True
        current["csrf_token"] = "frontend-csrf"

    page = client.get("/?view=assisted")

    assert page.status_code == 200
    assert b"Personal WhatsApp assistant" in page.data
    assert b"Relevant WhatsApp text" in page.data
    assert b"does not read your WhatsApp inbox or send messages" in page.data
    assert b"Check Google Calendar" in page.data


def test_personal_only_empty_queue_points_to_assisted_workflow(app_bundle, monkeypatch):
    app, _, _ = app_bundle
    client = app.test_client()
    with client.session_transaction() as current:
        current["operator_authenticated"] = True
        current["csrf_token"] = "frontend-csrf"

    original_readiness = app.extensions["scheduling"].readiness

    def personal_only_readiness():
        readiness = original_readiness()
        readiness["providers"]["whatsapp"]["enabled"] = False
        return readiness

    monkeypatch.setattr(app.extensions["scheduling"], "readiness", personal_only_readiness)

    page = client.get("/?view=scheduling")

    assert page.status_code == 200
    assert b"For personal WhatsApp," in page.data
    assert b'href="/?view=assisted"' in page.data
    assert b"New verified WhatsApp Business messages" not in page.data


def test_settings_explains_missing_google_oauth_file_and_hides_unavailable_action(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    with client.session_transaction() as current:
        current["operator_authenticated"] = True
        current["csrf_token"] = "frontend-csrf"

    settings_page = client.get("/?view=settings")

    assert settings_page.status_code == 200
    assert b"GOOGLE_CLIENT_SECRETS_FILE" in settings_page.data
    assert b"stored outside the repository" in settings_page.data
    assert b'href="/api/google/connect"' not in settings_page.data

    unavailable_action = client.get("/api/google/connect")
    assert unavailable_action.status_code == 302
    assert unavailable_action.headers["Location"] == "/?view=settings"
    assert b"Google OAuth is not configured" in client.get(unavailable_action.headers["Location"]).data
