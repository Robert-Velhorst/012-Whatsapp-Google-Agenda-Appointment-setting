from hashlib import sha256
from pathlib import Path
import re


def test_shared_html_template_has_noindex_description_for_operator_and_booking_pages(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()

    login = client.get("/login")
    assert login.status_code == 200
    assert b'<meta name="description"' in login.data
    assert b'<meta name="robots" content="noindex, nofollow">' in login.data

    service = app.extensions["scheduling"]
    store = app.extensions["store"]
    proposal_id = service.create_assisted_proposal("Can we schedule a 30 minute call next week?")
    store.mark_assisted_proposal_shared("default", proposal_id, "test")
    token = store.get_proposal("default", proposal_id)["booking_token"]
    booking = client.get(f"/book/{token}")

    assert booking.status_code == 200
    assert b'<meta name="description"' in booking.data
    assert b'<meta name="robots" content="noindex, nofollow">' in booking.data
    # The private link already identifies the scheduling request; asking the
    # recipient to re-enter contact details would restore the original friction.
    assert b'name="slot"' in booking.data
    assert b'name="consent"' in booking.data
    assert b'name="name"' not in booking.data
    assert b'name="email"' not in booking.data
    assert b'name="phone"' not in booking.data


def test_amber_status_color_meets_wcag_small_text_contrast(app_bundle):
    app, _, _ = app_bundle
    css = Path(app.static_folder, "app.css").read_text(encoding="utf-8")
    amber_colors = re.findall(r"--amber:(#[0-9a-fA-F]{6})", css)
    assert amber_colors

    def luminance(color):
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    foreground = luminance(amber_colors[-1])
    for background in ("#ffffff", "#fff6e7"):
        ratio = (luminance(background) + 0.05) / (foreground + 0.05)
        assert ratio >= 4.5, f"amber contrast is {ratio:.2f}:1 on {background}"


def test_favicon_is_linked_and_served(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()

    with client.get("/login") as page:
        assert page.status_code == 200
        assert b'rel="icon" type="image/svg+xml"' in page.data
        assert b"/static/favicon.svg" in page.data

    with client.get("/static/favicon.svg") as icon:
        assert icon.status_code == 200
        assert icon.mimetype == "image/svg+xml"
        assert b"<svg" in icon.data


def test_personal_whatsapp_assisted_screen_is_in_operator_navigation(app_bundle, monkeypatch):
    app, calendar, _ = app_bundle
    monkeypatch.setattr(calendar, "connected", lambda: False)
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
    assert b'href="/?view=settings">Connect Google Calendar in Settings</a>' in page.data


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
    assert unavailable_action.status_code == 400
    assert unavailable_action.get_json()["error"]["code"] == "google_credentials_missing"
    assert "GOOGLE_CLIENT_SECRETS_FILE" in unavailable_action.get_json()["error"]["message"]


def test_contacts_screen_exposes_valid_csrf_and_reauthenticated_delete_controls(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    contact_id = store.upsert_contact("default", "31600000098", "Europe/Amsterdam")
    client = app.test_client()
    with client.session_transaction() as current:
        current["operator_authenticated"] = True
        current["csrf_token"] = "contacts-csrf"

    page = client.get("/?view=contacts")
    html = page.get_data(as_text=True)

    assert page.status_code == 200
    assert f'id="contact-update-{contact_id}"' in html
    assert f'id="contact-delete-{contact_id}"' in html
    assert f'form="contact-update-{contact_id}"' in html
    assert f'form="contact-delete-{contact_id}"' in html
    assert f'href="/api/contacts/{contact_id}/export"' in html
    assert "Download JSON" in html
    assert 'name="csrf_token" value="contacts-csrf"' in html
    assert 'autocomplete="current-password" required' in html
    assert "Deletion permanently removes" in html
    assert "<tr>\n        <form" not in html
    with client.get("/static/app.css") as response:
        stylesheet = response.get_data(as_text=True)
    assert ".contacts-panel{max-width:100%;overflow-x:auto}" in stylesheet
    assert ".contacts-table th:nth-child(3),.contacts-table td:nth-child(3){display:table-cell}" in stylesheet


def test_static_assets_are_content_versioned_before_immutable_caching(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    digest = sha256((Path(app.static_folder) / "app.css").read_bytes()).hexdigest()[:16]

    with client.get("/login") as page:
        assert f"/static/app.css?v={digest}".encode() in page.data
    with client.get(f"/static/app.css?v={digest}") as versioned:
        assert versioned.status_code == 200
        assert versioned.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    with client.get("/static/app.css") as unversioned:
        assert unversioned.status_code == 200
        assert unversioned.headers["Cache-Control"] == "public, max-age=0, must-revalidate"


def test_responsive_scheduling_detail_remains_available_below_desktop_width(app_bundle):
    app, _, _ = app_bundle
    stylesheet = (Path(app.static_folder) / "app.css").read_text(encoding="utf-8")

    assert "@media(max-width:1180px){.desk-layout{grid-template-columns:1fr}.detail-rail{display:block}" in stylesheet


def test_primary_navigation_has_visible_keyboard_focus_indicator(app_bundle):
    app, _, _ = app_bundle
    stylesheet = (Path(app.static_folder) / "app.css").read_text(encoding="utf-8")

    assert ".nav-link:focus-visible{outline:2px solid var(--blue);outline-offset:2px}" in stylesheet


def test_compact_dashboard_actions_meet_minimum_target_size_and_have_focus_indicator(app_bundle):
    app, _, _ = app_bundle
    stylesheet = (Path(app.static_folder) / "app.css").read_text(encoding="utf-8")

    assert ".row-action,.pagination a,.text-button{min-width:24px;min-height:24px;display:inline-flex;align-items:center}" in stylesheet
    assert ".row-action{padding:3px 2px}" in stylesheet
    assert ".pagination a{padding:4px}" in stylesheet
    assert ".text-button{padding:3px 6px}" in stylesheet
    assert ":where(a,button,input,select,textarea):focus-visible{outline:2px solid var(--blue);outline-offset:2px}" in stylesheet


def test_green_status_color_meets_wcag_small_text_contrast(app_bundle):
    app, _, _ = app_bundle
    stylesheet = (Path(app.static_folder) / "app.css").read_text(encoding="utf-8")
    green_colors = re.findall(r"--green:(#[0-9a-fA-F]{6})", stylesheet)
    assert green_colors

    def luminance(color):
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    foreground = luminance(green_colors[-1])
    for background in ("#ffffff", "#ecf8f1"):
        ratio = (luminance(background) + 0.05) / (foreground + 0.05)
        assert ratio >= 4.5, f"green contrast is {ratio:.2f}:1 on {background}"


def test_mobile_primary_navigation_wraps_instead_of_hiding_destinations(app_bundle):
    app, _, _ = app_bundle
    stylesheet = (Path(app.static_folder) / "app.css").read_text(encoding="utf-8")

    assert (
        "@media(max-width:760px){.sidebar nav{display:grid;"
        "grid-template-columns:repeat(auto-fit,minmax(104px,1fr));overflow:visible}"
        ".nav-link{min-height:44px;gap:8px;padding:9px 8px;white-space:normal}}"
    ) in stylesheet


def test_settings_metadata_grid_reflows_on_narrow_mobile_viewports(app_bundle):
    app, _, _ = app_bundle
    stylesheet = (Path(app.static_folder) / "app.css").read_text(encoding="utf-8")

    assert (
        "@media(max-width:760px){.settings-block dl{"
        "grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}"
    ) in stylesheet

