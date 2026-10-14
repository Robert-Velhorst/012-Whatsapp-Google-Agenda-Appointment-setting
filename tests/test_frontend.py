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
