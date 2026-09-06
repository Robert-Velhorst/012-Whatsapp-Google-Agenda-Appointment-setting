from .conftest import post_webhook, webhook


def test_message_to_proposal_to_confirmation_to_calendar_event(app_bundle, auth_headers):
    app, calendar, whatsapp = app_bundle
    client = app.test_client()
    assert post_webhook(client, webhook()).get_json()["proposals"] == 1
    item = client.get("/api/requests", headers=auth_headers).get_json()["items"][0]

    sent = client.post(f"/api/proposals/{item['proposal_id']}/send", headers=auth_headers)
    assert sent.status_code == 200
    assert len(whatsapp.sent) == 1

    confirmed = post_webhook(client, webhook("wamid.2", body="The second one works for me"))
    assert confirmed.get_json()["confirmations"] == 1
    item = client.get("/api/requests", headers=auth_headers).get_json()["items"][0]
    assert item["status"] == "slot_confirmed"
    assert item["appointment_status"] == "pending_approval"

    booked = client.post(f"/api/appointments/{item['appointment_id']}/book", headers=auth_headers)
    assert booked.status_code == 200
    assert booked.get_json()["status"] == "booked"
    assert len(calendar.created) == 1
    assert len(whatsapp.sent) == 2
    final = client.get("/api/requests", headers=auth_headers).get_json()["items"][0]
    assert final["status"] == "booked"
    assert final["google_event_link"].startswith("https://calendar.google.com/")

    repeat = client.post(f"/api/appointments/{item['appointment_id']}/book", headers=auth_headers)
    assert repeat.status_code == 200 and repeat.get_json()["idempotent"] is True
    assert len(calendar.created) == 1


def test_public_booking_link_requires_consent(app_bundle, auth_headers):
    app, _, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    proposal = store.get_proposal("default", item["proposal_id"])
    token = proposal["booking_token"]
    assert client.get(f"/book/{token}").status_code == 200
    with client.session_transaction() as current:
        csrf = current["csrf_token"]
    assert client.post(f"/book/{token}", data={"slot": "0"}).status_code == 403
    rejected = client.post(f"/book/{token}", data={"csrf_token": csrf, "slot": "0"})
    assert rejected.status_code == 400
    accepted = client.post(f"/book/{token}", data={"csrf_token": csrf, "slot": "0", "consent": "yes"})
    assert accepted.status_code == 200
    assert b"Your time is confirmed" in accepted.data


def test_public_booking_link_expires(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    item = store.dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    proposal = store.get_proposal("default", item["proposal_id"])
    with store.connect() as db:
        db.execute("UPDATE proposals SET created_at='2020-01-01T00:00:00+00:00' WHERE id=?", (item["proposal_id"],))
    assert client.get(f"/book/{proposal['booking_token']}").status_code == 200
    with store.connect() as db:
        db.execute("UPDATE proposals SET sent_at='2020-01-01T00:00:00+00:00' WHERE id=?", (item["proposal_id"],))
    response = client.get(f"/book/{proposal['booking_token']}")
    assert response.status_code == 410
    assert b"booking link has expired" in response.data


def test_cancel_is_idempotent_and_calls_calendar(app_bundle, auth_headers):
    app, calendar, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    item = app.extensions["store"].dashboard("default")["items"][0]
    app.extensions["scheduling"].send_proposal(item["proposal_id"])
    post_webhook(client, webhook("wamid.2", body="1"))
    item = app.extensions["store"].dashboard("default")["items"][0]
    app.extensions["scheduling"].book_appointment(item["appointment_id"])
    result = client.post(f"/api/appointments/{item['appointment_id']}/cancel", headers=auth_headers)
    assert result.status_code == 200 and result.get_json()["changed"] is True
    assert calendar.cancelled == [f"event-{item['appointment_id']}"]
