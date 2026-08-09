from dataclasses import replace
from types import SimpleNamespace

from googleapiclient.errors import HttpError

from scheduler.calendar import GoogleCalendar
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
