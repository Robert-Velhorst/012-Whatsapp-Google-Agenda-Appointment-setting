from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from scheduler.store import utc_now
from scheduler.whatsapp import WhatsAppUnavailable

from .conftest import post_webhook, webhook


class FailingWhatsApp:
    def __init__(self, retry_safe: bool, message: str = "simulated provider failure"):
        self.retry_safe = retry_safe
        self.message = message

    def configured(self):
        return True

    def send_reply(self, recipient, message, reply_to=None):
        raise WhatsAppUnavailable(self.message, retry_safe=self.retry_safe)


@pytest.mark.parametrize(("retry_safe", "expected_status"), [(False, "manual_required"), (True, "send_failed")])
def test_proposal_send_distinguishes_ambiguous_delivery(app_bundle, retry_safe, expected_status):
    app, _, _ = app_bundle
    post_webhook(app.test_client(), webhook())
    store = app.extensions["store"]
    proposal_id = store.dashboard("default")["items"][0]["proposal_id"]
    app.extensions["scheduling"].whatsapp = FailingWhatsApp(retry_safe)

    with pytest.raises(WhatsAppUnavailable):
        app.extensions["scheduling"].send_proposal(proposal_id)

    assert store.get_proposal("default", proposal_id)["status"] == expected_status


@pytest.mark.parametrize(
    ("retry_safe", "expected_status", "error_code", "retryable"),
    [
        (True, "send_failed", "whatsapp_send_failed", True),
        (False, "manual_required", "whatsapp_delivery_unverified", False),
    ],
)
def test_proposal_send_api_maps_delivery_certainty_and_redacts_provider_details(
    app_bundle, auth_headers, retry_safe, expected_status, error_code, retryable,
):
    app, _, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    proposal_id = store.dashboard("default")["items"][0]["proposal_id"]
    secret_provider_detail = "PRIVATE_PROVIDER_RESPONSE_DO_NOT_DISCLOSE"
    app.extensions["scheduling"].whatsapp = FailingWhatsApp(retry_safe, secret_provider_detail)

    response = client.post(f"/api/proposals/{proposal_id}/send", headers=auth_headers)

    expected_message = (
        "WhatsApp confirmed that the message was not delivered. An explicit retry is available."
        if retry_safe
        else "WhatsApp delivery could not be verified. Check provider status before retrying."
    )
    assert response.status_code == 502
    assert response.get_json()["error"] == {
        "code": error_code,
        "message": expected_message,
        "retryable": retryable,
    }
    assert secret_provider_detail not in response.get_data(as_text=True)
    proposal = store.get_proposal("default", proposal_id)
    assert proposal["status"] == expected_status
    assert secret_provider_detail not in proposal["error_text"]
    assert secret_provider_detail not in str(store.recent_audit("default", 10))


def test_unexpected_proposal_provider_error_is_non_retryable_and_redacted(app_bundle, auth_headers):
    app, _, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    proposal_id = store.dashboard("default")["items"][0]["proposal_id"]
    secret_provider_detail = "PRIVATE_UNEXPECTED_PROVIDER_RESPONSE"

    class UnexpectedFailingWhatsApp(FailingWhatsApp):
        def send_reply(self, recipient, message, reply_to=None):
            raise RuntimeError(secret_provider_detail)

    app.extensions["scheduling"].whatsapp = UnexpectedFailingWhatsApp(False)
    response = client.post(f"/api/proposals/{proposal_id}/send", headers=auth_headers)

    assert response.status_code == 502
    assert response.get_json()["error"] == {
        "code": "whatsapp_delivery_unverified",
        "message": "WhatsApp delivery could not be verified. Check provider status before retrying.",
        "retryable": False,
    }
    assert secret_provider_detail not in response.get_data(as_text=True)
    proposal = store.get_proposal("default", proposal_id)
    assert proposal["status"] == "manual_required"
    assert secret_provider_detail not in proposal["error_text"]
    assert secret_provider_detail not in str(store.recent_audit("default", 10))


def test_operator_proposal_send_hides_unexpected_provider_details(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    proposal_id = store.dashboard("default")["items"][0]["proposal_id"]
    secret_provider_detail = "PRIVATE_UNEXPECTED_OPERATOR_PROVIDER_RESPONSE"

    class UnexpectedFailingWhatsApp(FailingWhatsApp):
        def send_reply(self, recipient, message, reply_to=None):
            raise RuntimeError(secret_provider_detail)

    app.extensions["scheduling"].whatsapp = UnexpectedFailingWhatsApp(False)
    with client.session_transaction() as current:
        current["operator_authenticated"] = True
        current["csrf_token"] = "provider-error-csrf"

    response = client.post(
        f"/actions/proposals/{proposal_id}/send",
        data={"csrf_token": "provider-error-csrf"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert secret_provider_detail not in response.get_data(as_text=True)
    assert b"WhatsApp delivery could not be verified" in response.data
    assert secret_provider_detail not in store.get_proposal("default", proposal_id)["error_text"]


def test_operator_can_reconcile_verified_delivery_without_resending(app_bundle):
    app, _, whatsapp = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    scheduling = app.extensions["scheduling"]
    proposal_id = store.dashboard("default")["items"][0]["proposal_id"]
    scheduling.whatsapp = FailingWhatsApp(retry_safe=False)

    with pytest.raises(WhatsAppUnavailable):
        scheduling.send_proposal(proposal_id)
    assert store.get_proposal("default", proposal_id)["status"] == "manual_required"

    with client.session_transaction() as current:
        current["operator_authenticated"] = True
        current["csrf_token"] = "reconcile-csrf"
    page = client.get("/?view=scheduling&request=1")
    assert b"WhatsApp delivery is unknown" in page.data
    assert b"I verified it was delivered" in page.data
    assert client.post(
        f"/actions/proposals/{proposal_id}/reconcile",
        data={"outcome": "delivered"},
    ).status_code == 403

    response = client.post(
        f"/actions/proposals/{proposal_id}/reconcile",
        data={"csrf_token": "reconcile-csrf", "outcome": "delivered"},
    )
    assert response.status_code == 302
    assert store.get_proposal("default", proposal_id)["status"] == "sent"
    assert store.request_detail("default", 1)["status"] == "awaiting_confirmation"
    assert whatsapp.sent == []
    with store.connect() as db:
        audit = db.execute(
            "SELECT detail_json FROM audit_events WHERE action='proposal.delivery_reconciled' AND entity_id=?",
            (str(proposal_id),),
        ).fetchone()
    assert '"outcome": "delivered"' in audit[0]


def test_verified_non_delivery_only_enables_a_separate_explicit_retry(app_bundle):
    app, _, whatsapp = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    scheduling = app.extensions["scheduling"]
    proposal_id = store.dashboard("default")["items"][0]["proposal_id"]
    scheduling.whatsapp = FailingWhatsApp(retry_safe=False)

    with pytest.raises(WhatsAppUnavailable):
        scheduling.send_proposal(proposal_id)
    store.reconcile_proposal_delivery("default", proposal_id, "not_delivered", "operator")
    assert store.get_proposal("default", proposal_id)["status"] == "send_failed"
    assert whatsapp.sent == []

    scheduling.whatsapp = whatsapp
    scheduling.send_proposal(proposal_id)
    assert len(whatsapp.sent) == 1
    assert store.get_proposal("default", proposal_id)["status"] == "sent"


def test_rate_limit_reservation_is_atomic(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]

    def reserve(_):
        try:
            return store.reserve_rate_event("default", "same-contact", "whatsapp.outbound", 5, 60)
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(reserve, range(24)))
    assert sum(results) == 5


def test_concurrent_proposal_send_reaches_provider_only_once(app_bundle):
    app, _, whatsapp = app_bundle
    post_webhook(app.test_client(), webhook())
    store = app.extensions["store"]
    proposal_id = store.dashboard("default")["items"][0]["proposal_id"]

    def send(_):
        try:
            app.extensions["scheduling"].send_proposal(proposal_id)
            return "sent"
        except ValueError:
            return "rejected"
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, range(2)))
    assert sorted(results) == ["rejected", "sent"]
    assert len(whatsapp.sent) == 1


def test_concurrent_confirmation_creates_one_appointment(app_bundle):
    app, _, _ = app_bundle
    post_webhook(app.test_client(), webhook())
    store = app.extensions["store"]
    proposal_id = store.dashboard("default")["items"][0]["proposal_id"]
    app.extensions["scheduling"].send_proposal(proposal_id)

    def confirm(_):
        try:
            return store.confirm_proposal("default", proposal_id, 0, "contact")
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(confirm, index) for index in range(2)]
        successes = 0
        rejected = 0
        for future in futures:
            try:
                future.result()
                successes += 1
            except ValueError:
                rejected += 1
    assert (successes, rejected) == (1, 1)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM appointments WHERE proposal_id=?", (proposal_id,)).fetchone()[0] == 1


def test_worker_recovers_stale_running_jobs_for_manual_review(app_bundle):
    app, _, _ = app_bundle
    store = app.extensions["store"]
    store.schedule_job("default", "appointment_reminder", "stale-running", utc_now().isoformat(), {"appointment_id": 999})
    with store.connect() as db:
        db.execute(
            "UPDATE background_jobs SET status='running',updated_at=? WHERE dedupe_key='stale-running'",
            ((utc_now() - timedelta(hours=1)).isoformat(),),
        )
    result = app.extensions["scheduling"].run_due_jobs()
    with store.connect() as db:
        row = db.execute("SELECT status,last_error FROM background_jobs WHERE dedupe_key='stale-running'").fetchone()
    assert result["recovered"] == 1
    assert row["status"] == "manual_required"
    assert "verify provider state" in row["last_error"]


def test_contact_timezone_is_preserved_and_used_in_new_proposals(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    contact = store.contacts("default")[0]
    store.update_contact(
        "default", contact["id"], display_name=contact["display_name"], email=contact["email"],
        timezone_name="Asia/Tokyo", language="en", consent_status=contact["consent_status"],
    )

    post_webhook(client, webhook("wamid.timezone", body="Could we schedule another 30 minute call next week?"))
    proposal = store.get_proposal("default", store.dashboard("default")["items"][0]["proposal_id"])
    expected = datetime.fromisoformat(proposal["slots"][0]).astimezone(ZoneInfo("Asia/Tokyo")).strftime("%H:%M")
    assert proposal["contact_timezone"] == "Asia/Tokyo"
    assert "Time zone: Asia/Tokyo" in proposal["reply_text"]
    assert expected in proposal["reply_text"]


def test_expired_whatsapp_proposal_cannot_be_confirmed(app_bundle):
    app, _, _ = app_bundle
    client = app.test_client()
    post_webhook(client, webhook())
    store = app.extensions["store"]
    proposal_id = store.dashboard("default")["items"][0]["proposal_id"]
    app.extensions["scheduling"].send_proposal(proposal_id)
    with store.connect() as db:
        sent_at = (utc_now() - timedelta(days=8)).isoformat()
        db.execute("UPDATE proposals SET sent_at=? WHERE id=?", (sent_at, proposal_id))

    result = post_webhook(client, webhook("wamid.expired", body="1")).get_json()
    assert result["confirmations"] == 0
    worker = app.extensions["scheduling"].run_due_jobs()
    assert worker["expired"] == 1
    assert store.get_proposal("default", proposal_id)["status"] == "expired"
