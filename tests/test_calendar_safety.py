from dataclasses import replace
from types import SimpleNamespace
from datetime import date, datetime, timedelta
import pytest

from googleapiclient.errors import HttpError

from scheduler.calendar import GoogleCalendar, CalendarUnavailable
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
