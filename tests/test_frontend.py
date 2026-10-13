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
