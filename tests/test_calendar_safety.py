import json
import os
import subprocess
import sys
import threading
import time as time_module
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from googleapiclient.errors import HttpError

from scheduler.calendar import CalendarUnavailable, GoogleCalendar
from scheduler.crypto import CryptoBox

INVALID_BUSY_INTERVALS = [
    pytest.param([{"start": "2030-01-07T10:45:00+01:00", "end": "2030-01-07T10:15:00+01:00"}], id="reversed"),
    pytest.param([{"start": "2030-01-07T10:15:00+01:00", "end": "2030-01-07T10:15:00+01:00"}], id="zero-length"),
    pytest.param([{"start": "2030-01-07T10:00:00", "end": "2030-01-07T10:30:00+01:00"}], id="timezone-free"),
    pytest.param([{"start": "invalid", "end": "2030-01-07T10:30:00+01:00"}], id="malformed"),
]


def _google_oauth_client(app):
    client = app.test_client()
    with client.session_transaction() as current:
        current["operator_authenticated"] = True
        current["google_oauth_state"] = "oauth-state"
    return client


class DeleteCall:
    def execute(self):
        raise HttpError(SimpleNamespace(status=404, reason="Not Found"), b'{}')


class Events:
    def delete(self, **kwargs):
        return DeleteCall()


class Service:
    def events(self):
        return Events()


def test_calendar_cancel_treats_missing_event_as_idempotent(app_bundle):
    app, _, _ = app_bundle
    calendar = GoogleCalendar(app.extensions["settings"], CryptoBox("test-encryption-key"))
    calendar._service = lambda: Service()
    assert calendar.cancel_event("already-deleted") is None


def test_google_oauth_connect_requires_operator_login(app_bundle):
    app, _, _ = app_bundle
    response = app.test_client().get("/api/google/connect")

    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "authentication_required"


def test_google_oauth_denial_does_not_exchange_a_missing_code(app_bundle):
    app, calendar, _ = app_bundle
    calendar.exchange_code = lambda *_args: pytest.fail("OAuth denial must not exchange a code")
    client = _google_oauth_client(app)

    response = client.get("/api/google/callback?state=oauth-state&error=access_denied")

    assert response.status_code == 302
    dashboard = client.get(response.headers["Location"])
    assert b"Google Calendar authorization was cancelled" in dashboard.data
    assert b"access_denied" not in dashboard.data


def test_google_oauth_callback_rejects_invalid_state_without_exchange(app_bundle):
    app, calendar, _ = app_bundle
    calendar.exchange_code = lambda *_args: pytest.fail("Invalid OAuth state must not exchange a code")
    client = _google_oauth_client(app)

    response = client.get("/api/google/callback?state=attacker-state&code=synthetic-code")

    assert response.status_code == 400
    assert b"Invalid Google OAuth state" in response.data


@pytest.mark.parametrize("query", ["code=synthetic-code", "state=attacker-state&code=synthetic-code"])
def test_google_oauth_callback_rejects_missing_session_state(app_bundle, query):
    app, calendar, _ = app_bundle
    calendar.exchange_code = lambda *_args: pytest.fail("Missing OAuth state must not exchange a code")

    response = app.test_client().get(f"/api/google/callback?{query}")

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_oauth_state"


def test_google_oauth_success_audits_only_after_exchange(app_bundle):
    app, calendar, _ = app_bundle
    exchanges = []
    calendar.exchange_code = lambda authorization_response, redirect_uri: exchanges.append((authorization_response, redirect_uri))
    client = _google_oauth_client(app)

    response = client.get("/api/google/callback?state=oauth-state&code=synthetic-code")

    assert response.status_code == 302
    assert len(exchanges) == 1
    assert exchanges[0][1] == "http://localhost/api/google/callback"
    audit = app.extensions["store"].recent_audit("default")
    assert any(item["action"] == "provider.google_connected" for item in audit)


def test_google_oauth_exchange_failure_is_sanitized_and_retryable(app_bundle, caplog):
    app, calendar, _ = app_bundle
    calendar.exchange_code = lambda *_args: (_ for _ in ()).throw(
        RuntimeError("PRIVATE_PROVIDER_RESPONSE access_token=do-not-disclose")
    )
    client = _google_oauth_client(app)

    response = client.get("/api/google/callback?state=oauth-state&code=synthetic-code")

    assert response.status_code == 302
    dashboard = client.get(response.headers["Location"])
    assert b"Google Calendar connection could not be completed" in dashboard.data
    assert b"PRIVATE_PROVIDER_RESPONSE" not in dashboard.data
    assert "PRIVATE_PROVIDER_RESPONSE" not in caplog.text


def test_calendar_lookup_verifies_event_id_marker_and_interval(app_bundle):
    app, _, _ = app_bundle
    calendar = GoogleCalendar(app.extensions["settings"], CryptoBox("test-encryption-key"))
    appointment = {
        "workspace_id": "default", "id": 12,
        "start_at": "2030-01-07T10:00:00+01:00", "end_at": "2030-01-07T10:30:00+01:00",
    }
    event_id = calendar._event_id(appointment["workspace_id"], appointment["id"])
    event = {
        "id": event_id,
        "status": "confirmed",
        "extendedProperties": {"private": {"agendaRelayAppointmentId": "12"}},
        "start": {"dateTime": "2030-01-07T09:00:00+00:00"},
        "end": {"dateTime": "2030-01-07T09:30:00+00:00"},
        "htmlLink": "https://calendar.google.com/event/12",
    }

    class GetEvents:
        def get(self, **kwargs):
            assert kwargs == {"calendarId": "primary", "eventId": event_id}
            return SimpleNamespace(execute=lambda: event)

    calendar._service = lambda: SimpleNamespace(events=lambda: GetEvents())

    assert calendar.find_appointment_event(appointment) == {"id": event_id, "htmlLink": event["htmlLink"]}


def test_booking_attempt_event_ids_preserve_first_attempt_and_separate_retries():
    first = GoogleCalendar._event_id("default", 12)
    explicit_first = GoogleCalendar._event_id("default", 12, 1)
    retry = GoogleCalendar._event_id("default", 12, 2)

    assert first == explicit_first
    assert retry != first
    assert set(retry) <= set("0123456789abcdefghijklmnopqrstuv")


def test_calendar_insert_uses_new_id_after_confirmed_duplicate_conflict(app_bundle):
    app, _, _ = app_bundle
    calendar = GoogleCalendar(app.extensions["settings"], CryptoBox("test-encryption-key"))
    appointment = {
        "workspace_id": "default", "id": 12, "booking_attempt": 1,
        "title": "Consultation", "start_at": "2030-01-07T10:00:00+01:00",
        "end_at": "2030-01-07T10:30:00+01:00", "timezone": "Europe/Amsterdam",
    }
    inserted_ids = []

    class Events:
        def insert(self, *, calendarId, body, sendUpdates):
            inserted_ids.append(body["id"])
            if len(inserted_ids) == 1:
                return SimpleNamespace(execute=lambda: (_ for _ in ()).throw(
                    HttpError(SimpleNamespace(status=409, reason="Conflict"), b'{}')
                ))
            return SimpleNamespace(execute=lambda: {"id": body["id"], "status": "confirmed"})

        def get(self, *, calendarId, eventId):
            assert eventId == GoogleCalendar._event_id("default", 12, 1)
            return SimpleNamespace(execute=lambda: {"id": eventId, "status": "cancelled"})

    calendar._service = lambda: SimpleNamespace(events=lambda: Events())

    with pytest.raises(CalendarUnavailable, match="already exists"):
        calendar.create_event(appointment)

    appointment["booking_attempt"] = 2
    result = calendar.create_event(appointment)

    assert result["id"] == GoogleCalendar._event_id("default", 12, 2)
    assert inserted_ids == [GoogleCalendar._event_id("default", 12, attempt) for attempt in (1, 2)]


def test_calendar_lookup_returns_none_for_missing_event(app_bundle):
    app, _, _ = app_bundle
    calendar = GoogleCalendar(app.extensions["settings"], CryptoBox("test-encryption-key"))

    class MissingEvents:
        def get(self, **kwargs):
            return DeleteCall()

    calendar._service = lambda: SimpleNamespace(events=lambda: MissingEvents())

    assert calendar.find_appointment_event({"workspace_id": "default", "id": 12}) is None


@pytest.mark.parametrize("mutation", ["marker", "time", "status"])
def test_calendar_lookup_rejects_mismatched_event(app_bundle, mutation):
    app, _, _ = app_bundle
    calendar = GoogleCalendar(app.extensions["settings"], CryptoBox("test-encryption-key"))
    appointment = {
        "workspace_id": "default", "id": 12,
        "start_at": "2030-01-07T10:00:00+01:00", "end_at": "2030-01-07T10:30:00+01:00",
    }
    event = {
        "id": calendar._event_id("default", 12),
        "status": "confirmed",
        "extendedProperties": {"private": {"agendaRelayAppointmentId": "12"}},
        "start": {"dateTime": appointment["start_at"]},
        "end": {"dateTime": appointment["end_at"]},
    }
    if mutation == "marker":
        event["extendedProperties"]["private"]["agendaRelayAppointmentId"] = "99"
    elif mutation == "time":
        event["start"]["dateTime"] = "2030-01-07T11:00:00+01:00"
    else:
        event["status"] = "tentative"
    calendar._service = lambda: SimpleNamespace(events=lambda: SimpleNamespace(get=lambda **kwargs: SimpleNamespace(execute=lambda: event)))

    with pytest.raises(CalendarUnavailable):
        calendar.find_appointment_event(appointment)


def test_google_token_write_is_atomic_and_encrypted(app_bundle, tmp_path):
    app, _, _ = app_bundle
    token_path = tmp_path / "credentials" / "google-token.json"
    settings = replace(app.extensions["settings"], google_token_file=str(token_path))
    crypto = CryptoBox("test-encryption-key")
    calendar = GoogleCalendar(settings, crypto)

    calendar._write_token('{"refresh_token":"secret"}')

    stored = token_path.read_text(encoding="utf-8")
    assert stored.startswith("enc:")
    assert crypto.decrypt(stored) == '{"refresh_token":"secret"}'
    assert list(token_path.parent.glob("*.tmp")) == []


@pytest.mark.parametrize(
    ("refresh_error", "expected_message"),
    [
        ("refresh", "authorization could not be refreshed; reconnect it"),
        ("transport", "token refresh could not reach Google; retry"),
    ],
)
def test_expired_google_token_refresh_failures_are_actionable_and_do_not_leak_provider_details(
    app_bundle, tmp_path, monkeypatch, refresh_error, expected_message
):
    app, _, _ = app_bundle
    token_path = tmp_path / "credentials" / "google-token.json"
    settings = replace(app.extensions["settings"], google_token_file=str(token_path))
    crypto = CryptoBox("test-encryption-key")
    calendar = GoogleCalendar(settings, crypto)
    original_token = '{"token":"expired","refresh_token":"private-refresh-token"}'
    token_path.parent.mkdir(parents=True)
    token_path.write_text(crypto.encrypt(original_token), encoding="utf-8")

    class FakeCredentials:
        expired = True
        valid = False
        refresh_token = "private-refresh-token"

        @classmethod
        def from_authorized_user_info(cls, info, scopes):
            return cls()

        def refresh(self, request):
            if refresh_error == "refresh":
                from google.auth.exceptions import RefreshError

                raise RefreshError("private provider response: invalid_grant with secret detail")
            from google.auth.exceptions import TransportError

            raise TransportError("private network response detail")

        def to_json(self):
            raise AssertionError("a failed refresh must not be persisted")

    monkeypatch.setattr("scheduler.calendar.Credentials", FakeCredentials)
    monkeypatch.setattr("scheduler.calendar.Request", lambda: object())

    with pytest.raises(CalendarUnavailable, match=expected_message) as error:
        calendar._credentials()

    assert "private" not in str(error.value)
    assert crypto.decrypt(token_path.read_text(encoding="utf-8")) == original_token
    assert list(token_path.parent.glob("*.tmp")) == []


@pytest.mark.parametrize(
    ("failure_message", "expected_readiness_detail"),
    [
        (
            "Google Calendar token refresh could not reach Google; retry after connectivity is restored.",
            "Google Calendar token refresh could not reach Google; retry after connectivity is restored.",
        ),
        (
            "Google Calendar authorization could not be refreshed; reconnect it from the operator dashboard.",
            "Google Calendar authorization could not be refreshed; reconnect it from the operator dashboard.",
        ),
    ],
)
def test_provider_readiness_distinguishes_google_retry_from_reconnect(app_bundle, monkeypatch, failure_message, expected_readiness_detail):
    app, _, _ = app_bundle
    calendar = GoogleCalendar(app.extensions["settings"])

    def fail_credentials():
        raise CalendarUnavailable(failure_message)

    monkeypatch.setattr(calendar, "_credentials", fail_credentials)
    app.extensions["scheduling"].calendar = calendar

    provider = app.extensions["scheduling"].readiness()["providers"]["google_calendar"]

    assert provider["ready"] is False
    assert provider["detail"] == expected_readiness_detail


def test_provider_readiness_sanitizes_unexpected_calendar_credential_errors(app_bundle, monkeypatch):
    app, _, _ = app_bundle
    calendar = GoogleCalendar(app.extensions["settings"])
    secret_detail = "PRIVATE_GOOGLE_TOKEN_RESPONSE"

    def fail_credentials():
        raise RuntimeError(secret_detail)

    monkeypatch.setattr(calendar, "_credentials", fail_credentials)
    app.extensions["scheduling"].calendar = calendar

    provider = app.extensions["scheduling"].readiness()["providers"]["google_calendar"]

    assert provider["ready"] is False
    assert provider["detail"] == "Google Calendar credentials could not be validated; reconnect it from the operator dashboard."
    assert secret_detail not in provider["detail"]


def test_concurrent_expired_token_reads_refresh_once_and_return_current_credentials(app_bundle, tmp_path, monkeypatch):
    app, _, _ = app_bundle
    token_path = tmp_path / "credentials" / "google-token.json"
    settings = replace(app.extensions["settings"], google_token_file=str(token_path))
    crypto = CryptoBox("test-encryption-key")
    calendar = GoogleCalendar(settings, crypto)
    token_path.parent.mkdir(parents=True)
    token_path.write_text(crypto.encrypt('{"token":"old"}'), encoding="utf-8")

    caller_count = 8
    initial_reads = threading.Barrier(caller_count)
    counter_lock = threading.Lock()
    read_count = 0
    refresh_count = 0

    class FakeCredentials:
        def __init__(self, token):
            self.token = token
            self.refresh_token = "refresh-token"

        @classmethod
        def from_authorized_user_info(cls, info, scopes):
            nonlocal read_count
            with counter_lock:
                read_count += 1
                current_read = read_count
            if current_read <= caller_count:
                initial_reads.wait(timeout=5)
            return cls(info["token"])

        @property
        def expired(self):
            return self.token == "old"

        @property
        def valid(self):
            return self.token == "new"

        def refresh(self, request):
            nonlocal refresh_count
            with counter_lock:
                refresh_count += 1
            self.token = "new"

        def to_json(self):
            return json.dumps({"token": self.token})

    monkeypatch.setattr("scheduler.calendar.Credentials", FakeCredentials)
    monkeypatch.setattr("scheduler.calendar.Request", lambda: object())

    with ThreadPoolExecutor(max_workers=caller_count) as pool:
        credentials = list(pool.map(lambda _: calendar._credentials(), range(caller_count)))

    assert refresh_count == 1
    assert all(item.valid and item.token == "new" for item in credentials)
    stored = crypto.decrypt(token_path.read_text(encoding="utf-8"))
    assert json.loads(stored) == {"token": "new"}
    assert list(token_path.parent.glob("*.tmp")) == []


def test_separate_calendar_instances_share_expired_token_refresh(app_bundle, tmp_path, monkeypatch):
    app, _, _ = app_bundle
    token_path = tmp_path / "credentials" / "google-token.json"
    settings = replace(app.extensions["settings"], google_token_file=str(token_path))
    crypto = CryptoBox("test-encryption-key")
    calendars = [GoogleCalendar(settings, crypto), GoogleCalendar(settings, crypto)]
    token_path.parent.mkdir(parents=True)
    token_path.write_text(crypto.encrypt('{"token":"old"}'), encoding="utf-8")

    initial_reads = threading.Barrier(2)
    lock_reload_reads = threading.Barrier(2)
    counter_lock = threading.Lock()
    reads = 0
    refreshes = 0

    class FakeCredentials:
        def __init__(self, token):
            self.token = token
            self.refresh_token = "refresh-token"

        @classmethod
        def from_authorized_user_info(cls, info, scopes):
            nonlocal reads
            with counter_lock:
                reads += 1
                current_read = reads
            if current_read <= 2:
                initial_reads.wait(timeout=5)
            elif current_read <= 4:
                try:
                    lock_reload_reads.wait(timeout=0.25)
                except threading.BrokenBarrierError:
                    pass
            return cls(info["token"])

        @property
        def expired(self):
            return self.token == "old"

        @property
        def valid(self):
            return self.token.startswith("new-")

        def refresh(self, request):
            nonlocal refreshes
            with counter_lock:
                refreshes += 1
                number = refreshes
            self.token = f"new-{number}"

        def to_json(self):
            return json.dumps({"token": self.token})

    monkeypatch.setattr("scheduler.calendar.Credentials", FakeCredentials)
    monkeypatch.setattr("scheduler.calendar.Request", lambda: object())

    with ThreadPoolExecutor(max_workers=2) as pool:
        credentials = list(pool.map(lambda calendar: calendar._credentials(), calendars))

    assert refreshes == 1
    assert all(item.valid for item in credentials)
    stored = crypto.decrypt(token_path.read_text(encoding="utf-8"))
    assert json.loads(stored)["token"].startswith("new-")


def test_token_refresh_guard_serializes_separate_processes(tmp_path):
    token_path = tmp_path / "credentials" / "google-token.json"
    marker_path = tmp_path / "events.txt"
    ready_path = tmp_path / "ready"
    start_path = tmp_path / "start"
    ready_path.mkdir()
    script = """
import os
import time
from pathlib import Path
from scheduler.calendar import _token_refresh_guard

token_path = Path(os.environ["TOKEN_PATH"])
marker_path = Path(os.environ["MARKER_PATH"])
ready_path = Path(os.environ["READY_PATH"])
start_path = Path(os.environ["START_PATH"])
ready_path.joinpath(str(os.getpid())).touch()
deadline = time.monotonic() + 5
while not start_path.exists() and time.monotonic() < deadline:
    time.sleep(0.01)
if not start_path.exists():
    raise SystemExit("parent did not release workers")
with _token_refresh_guard(token_path):
    with marker_path.open("a", encoding="utf-8") as handle:
        handle.write("start\\n")
    time.sleep(0.15)
    with marker_path.open("a", encoding="utf-8") as handle:
        handle.write("end\\n")
"""
    child_env = os.environ.copy()
    child_env.update(
        {
            "TOKEN_PATH": str(token_path),
            "MARKER_PATH": str(marker_path),
            "READY_PATH": str(ready_path),
            "START_PATH": str(start_path),
        }
    )
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    deadline = time_module.monotonic() + 10
    while time_module.monotonic() < deadline and len(list(ready_path.glob("*"))) < 2:
        time_module.sleep(0.02)
    assert len(list(ready_path.glob("*"))) == 2
    start_path.touch()

    results = [worker.communicate(timeout=10) for worker in workers]
    assert [worker.returncode for worker in workers] == [0, 0], results
    assert marker_path.read_text(encoding="utf-8").splitlines() == ["start", "end", "start", "end"]


def test_free_slots_uses_one_batched_freebusy_query_for_search_window(app_bundle):
    app, _, _ = app_bundle
    calendar = GoogleCalendar(app.extensions["settings"])
    start_day = date(2030, 1, 7)  # Monday
    busy = []
    for offset in range(14):
        day = start_day + timedelta(days=offset)
        if day.weekday() < 5:
            busy.append({
                "start": f"{day.isoformat()}T09:00:00+01:00",
                "end": f"{day.isoformat()}T17:00:00+01:00",
            })
    calls = []

    class FreeBusy:
        def query(self, *, body):
            calls.append(body)
            return SimpleNamespace(execute=lambda: {"calendars": {"primary": {"busy": busy}}})

    calendar._service = lambda: SimpleNamespace(freebusy=lambda: FreeBusy())

    slots = calendar.free_slots(start_day, 30)

    assert len(calls) == 1
    assert calls[0]["timeMin"] == "2030-01-07T00:00:00+01:00"
    assert calls[0]["timeMax"] == "2030-01-28T00:00:00+01:00"
    assert [slot.isoformat() for slot in slots] == [
        "2030-01-21T09:00:00+01:00",
        "2030-01-21T09:30:00+01:00",
        "2030-01-21T10:00:00+01:00",
    ]


def test_free_slots_prioritizes_requested_time_then_closest_alternatives(app_bundle):
    app, _, _ = app_bundle
    calendar = GoogleCalendar(app.extensions["settings"])
    calendar.settings = replace(
        calendar.settings, business_hours_start=9, business_hours_end=17, slot_interval_minutes=30,
    )
    calendar._service = lambda: SimpleNamespace(
        freebusy=lambda: SimpleNamespace(
            query=lambda **kw: SimpleNamespace(execute=lambda: {"calendars": {"primary": {"busy": []}}})
        )
    )

    slots = calendar.free_slots(date(2030, 1, 7), 30, preferred_time=time(15))

    assert [slot.strftime("%H:%M") for slot in slots] == ["15:00", "14:30", "15:30"]


@pytest.mark.parametrize("busy", INVALID_BUSY_INTERVALS)
def test_free_slots_rejects_invalid_provider_busy_intervals(app_bundle, busy):
    app, _, _ = app_bundle
    calendar = GoogleCalendar(app.extensions["settings"])
    calendar._service = lambda: SimpleNamespace(freebusy=lambda: SimpleNamespace(query=lambda **kw: SimpleNamespace(execute=lambda: {"calendars": {"primary": {"busy": busy}}})))

    with pytest.raises(CalendarUnavailable, match="invalid busy interval"):
        calendar.free_slots(date(2030, 1, 7), 30)


@pytest.mark.parametrize("response", [{}, {"calendars": {}}, {"calendars": {"primary": {}}}])
def test_missing_availability_is_not_treated_as_free(app_bundle, response):
    app, _, _ = app_bundle
    calendar = GoogleCalendar(app.extensions["settings"])
    calendar._service = lambda: SimpleNamespace(freebusy=lambda: SimpleNamespace(query=lambda **kw: SimpleNamespace(execute=lambda: response)))
    with pytest.raises(CalendarUnavailable):
        calendar.free_slots(date(2030, 1, 7), 30)


@pytest.mark.parametrize("busy,expected", [([], True), ([{"start": "2030-01-07T10:00:00+01:00", "end": "2030-01-07T10:30:00+01:00"}], False)])
def test_confirmed_slot_availability_recheck(app_bundle, busy, expected):
    app, _, _ = app_bundle
    calendar = GoogleCalendar(app.extensions["settings"])
    calendar._service = lambda: SimpleNamespace(freebusy=lambda: SimpleNamespace(query=lambda **kw: SimpleNamespace(execute=lambda: {"calendars": {"primary": {"busy": busy}}})))
    start = datetime.fromisoformat("2030-01-07T10:00:00+01:00")
    assert calendar.is_slot_available(start, start + timedelta(minutes=30)) is expected


def test_calendar_reschedule_patches_only_event_time_fields(app_bundle):
    app, _, _ = app_bundle
    calendar = GoogleCalendar(app.extensions["settings"])
    calls = []

    class Events:
        def patch(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(execute=lambda: {"id": "event-1"})

    calendar._service = lambda: SimpleNamespace(events=lambda: Events())

    result = calendar.update_event(
        "event-1", "2030-01-07T10:00:00+01:00", "2030-01-07T10:30:00+01:00", "Europe/Amsterdam",
    )

    assert result == {"id": "event-1"}
    assert calls == [{
        "calendarId": "primary",
        "eventId": "event-1",
        "body": {
            "start": {"dateTime": "2030-01-07T10:00:00+01:00", "timeZone": "Europe/Amsterdam"},
            "end": {"dateTime": "2030-01-07T10:30:00+01:00", "timeZone": "Europe/Amsterdam"},
        },
        "sendUpdates": "all",
    }]


@pytest.mark.parametrize("busy", INVALID_BUSY_INTERVALS)
def test_confirmed_slot_recheck_fails_closed_on_invalid_provider_busy_intervals(app_bundle, busy):
    app, _, _ = app_bundle
    calendar = GoogleCalendar(app.extensions["settings"])
    calendar._service = lambda: SimpleNamespace(freebusy=lambda: SimpleNamespace(query=lambda **kw: SimpleNamespace(execute=lambda: {"calendars": {"primary": {"busy": busy}}})))
    start = datetime.fromisoformat("2030-01-07T10:00:00+01:00")

    with pytest.raises(CalendarUnavailable, match="invalid busy interval"):
        calendar.is_slot_available(start, start + timedelta(minutes=30))
