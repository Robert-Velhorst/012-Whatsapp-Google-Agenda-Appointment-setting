import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest
from googleapiclient.errors import HttpError

from scheduler.calendar import CalendarUnavailable, GoogleCalendar
from scheduler.crypto import CryptoBox


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
