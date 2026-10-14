from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from scheduler.whatsapp import WhatsAppClient, WhatsAppUnavailable


class FakeResponse:
    def __init__(self, data, status_code=200):
        self.data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("provider response body must not be surfaced")

    def json(self):
        if isinstance(self.data, BaseException):
            raise self.data
        return self.data


def client() -> WhatsAppClient:
    return WhatsAppClient(SimpleNamespace(
        whatsapp_access_token="synthetic-access-token",
        whatsapp_phone_number_id="123456789",
        whatsapp_graph_api_version="v23.0",
    ))


def test_send_reply_uses_expected_cloud_api_request(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse({"messages": [{"id": "wamid.synthetic"}]})

    monkeypatch.setattr("scheduler.whatsapp.requests.post", post)
    result = client().send_reply("31612345678", "Proposed time slots", "wamid.inbound")

    assert result["messages"][0]["id"] == "wamid.synthetic"
    assert calls == [(
        "https://graph.facebook.com/v23.0/123456789/messages",
        {
            "headers": {"Authorization": "Bearer synthetic-access-token"},
            "json": {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": "31612345678",
                "type": "text",
                "text": {"preview_url": False, "body": "Proposed time slots"},
                "context": {"message_id": "wamid.inbound"},
            },
            "timeout": (5, 20),
        },
    )]


def test_send_template_uses_supported_language_and_parameters(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "scheduler.whatsapp.requests.post",
        lambda url, **kwargs: (calls.append((url, kwargs)) or FakeResponse({"messages": [{"id": "wamid.template"}]})),
    )

    client().send_template("31612345678", "appointment_reminder", "nl", ["Intro call", "15-10-2026 10:00"])

    payload = calls[0][1]["json"]
    assert payload["template"]["language"] == {"code": "nl"}
    assert payload["template"]["components"][0]["parameters"] == [
        {"type": "text", "text": "Intro call"},
        {"type": "text", "text": "15-10-2026 10:00"},
    ]


@pytest.mark.parametrize("data", [None, [], {}, {"messages": []}, {"messages": [{}]}, {"messages": [{"id": ""}]}, {"messages": "invalid"}])
def test_success_response_without_a_message_id_is_ambiguous(monkeypatch, data):
    monkeypatch.setattr("scheduler.whatsapp.requests.post", lambda *_args, **_kwargs: FakeResponse(data))

    with pytest.raises(WhatsAppUnavailable, match="no message identifier") as error:
        client().send_reply("31612345678", "Proposal")

    assert not error.value.retry_safe
    assert "synthetic-access-token" not in str(error.value)


def test_malformed_success_json_is_ambiguous(monkeypatch):
    monkeypatch.setattr("scheduler.whatsapp.requests.post", lambda *_args, **_kwargs: FakeResponse(ValueError("sensitive response")))

    with pytest.raises(WhatsAppUnavailable, match="unreadable success response") as error:
        client().send_reply("31612345678", "Proposal")

    assert not error.value.retry_safe
    assert "sensitive response" not in str(error.value)


@pytest.mark.parametrize("failure", [
    requests.Timeout("synthetic timeout"),
    requests.ConnectionError("synthetic connection error"),
    requests.RequestException("synthetic request detail"),
])
def test_network_failure_is_ambiguous_and_does_not_surface_request_details(monkeypatch, failure):
    monkeypatch.setattr("scheduler.whatsapp.requests.post", lambda *_args, **_kwargs: (_ for _ in ()).throw(failure))

    with pytest.raises(WhatsAppUnavailable) as error:
        client().send_reply("31612345678", "Proposal")

    assert not error.value.retry_safe
    assert "synthetic" not in str(error.value)


def test_malformed_success_response_stays_in_manual_review(app_bundle, monkeypatch):
    from .conftest import post_webhook, webhook

    app, _, _ = app_bundle
    post_webhook(app.test_client(), webhook())
    store = app.extensions["store"]
    proposal_id = store.dashboard("default")["items"][0]["proposal_id"]
    app.extensions["scheduling"].whatsapp = WhatsAppClient(app.extensions["settings"])
    monkeypatch.setattr(
        "scheduler.whatsapp.requests.post",
        lambda *_args, **_kwargs: FakeResponse({"messages": [{}]}),
    )

    with pytest.raises(WhatsAppUnavailable):
        app.extensions["scheduling"].send_proposal(proposal_id)

    proposal = store.get_proposal("default", proposal_id)
    assert proposal["status"] == "manual_required"
    assert proposal["provider_message_id"] is None


@pytest.mark.parametrize(("status_code", "retry_safe"), [(400, True), (429, True), (500, False)])
def test_http_errors_report_only_status_and_classify_retry_safety(monkeypatch, status_code, retry_safe):
    monkeypatch.setattr("scheduler.whatsapp.requests.post", lambda *_args, **_kwargs: FakeResponse({}, status_code))

    with pytest.raises(WhatsAppUnavailable, match=f"HTTP {status_code}") as error:
        client().send_reply("31612345678", "Proposal")

    assert error.value.retry_safe is retry_safe
    assert "provider response body" not in str(error.value)


def test_missing_credentials_fail_before_network_request(monkeypatch):
    settings = SimpleNamespace(whatsapp_access_token="", whatsapp_phone_number_id="123", whatsapp_graph_api_version="v23.0")
    monkeypatch.setattr("scheduler.whatsapp.requests.post", lambda *_args, **_kwargs: pytest.fail("must not make a request"))

    with pytest.raises(WhatsAppUnavailable, match="credentials are not configured") as error:
        WhatsAppClient(settings).send_reply("31612345678", "Proposal")

    assert error.value.retry_safe
