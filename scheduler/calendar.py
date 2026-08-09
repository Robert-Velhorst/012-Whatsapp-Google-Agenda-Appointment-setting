from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import Settings
from .crypto import CryptoBox

SCOPES = [
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events",
]


class CalendarUnavailable(RuntimeError):
    pass


class GoogleCalendar:
    def __init__(self, settings: Settings, crypto: CryptoBox | None = None):
        self.settings = settings
        self.crypto = crypto or CryptoBox(settings.data_encryption_key)

    def authorization_url(self, redirect_uri: str, state: str) -> str:
        flow = Flow.from_client_secrets_file(self.settings.google_client_secrets_file, scopes=SCOPES, state=state, redirect_uri=redirect_uri)
        url, _ = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
        return url

    def exchange_code(self, authorization_response: str, redirect_uri: str) -> None:
        flow = Flow.from_client_secrets_file(self.settings.google_client_secrets_file, scopes=SCOPES, redirect_uri=redirect_uri)
        flow.fetch_token(authorization_response=authorization_response)
        self._write_token(flow.credentials.to_json())

    def connected(self) -> bool:
        try:
            self._credentials()
            return True
        except Exception:
            return False

    def free_slots(self, start_day, duration_minutes: int, count: int = 3) -> list[datetime]:
        service = self._service()
        tz = ZoneInfo(self.settings.timezone)
        day = start_day
        slots: list[datetime] = []
        now = datetime.now(tz)
        for _ in range(21):
            if day.weekday() < 5:
                lower = datetime.combine(day, time(self.settings.business_hours_start), tzinfo=tz)
                upper = datetime.combine(day, time(self.settings.business_hours_end), tzinfo=tz)
                if lower.date() == now.date() and lower < now:
                    interval = self.settings.slot_interval_minutes
                    minutes = ((now.minute + interval - 1) // interval) * interval
                    lower = now.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minutes)
                busy_response = service.freebusy().query(body={
                    "timeMin": lower.isoformat(), "timeMax": upper.isoformat(), "timeZone": self.settings.timezone,
                    "items": [{"id": self.settings.google_calendar_id}],
                }).execute()
                calendar_data = busy_response.get("calendars", {}).get(self.settings.google_calendar_id, {})
                if calendar_data.get("errors"):
                    raise CalendarUnavailable(f"Google Calendar FreeBusy error: {calendar_data['errors']}")
                ranges = [
                    (datetime.fromisoformat(item["start"]).astimezone(tz), datetime.fromisoformat(item["end"]).astimezone(tz))
                    for item in calendar_data.get("busy", [])
                ]
                candidate = lower
                while candidate + timedelta(minutes=duration_minutes) <= upper:
                    end = candidate + timedelta(minutes=duration_minutes)
                    if candidate >= now and not any(candidate < busy_end and end > busy_start for busy_start, busy_end in ranges):
                        slots.append(candidate)
                        if len(slots) == count:
                            return slots
                    candidate += timedelta(minutes=self.settings.slot_interval_minutes)
            day += timedelta(days=1)
        return slots

    def create_event(self, appointment: dict) -> dict:
        service = self._service()
        event_id = self._event_id(appointment["workspace_id"], appointment["id"])
        body = {
            "id": event_id,
            "summary": appointment["title"],
            "description": "Scheduled from a consented WhatsApp conversation by Agenda Relay.",
            "start": {"dateTime": appointment["start_at"], "timeZone": appointment["timezone"]},
            "end": {"dateTime": appointment["end_at"], "timeZone": appointment["timezone"]},
            "extendedProperties": {"private": {"agendaRelayAppointmentId": str(appointment["id"])}},
        }
        if appointment.get("email"):
            body["attendees"] = [{"email": appointment["email"]}]
        try:
            return service.events().insert(
                calendarId=self.settings.google_calendar_id,
                body=body,
                sendUpdates="all" if appointment.get("email") else "none",
            ).execute()
        except HttpError as exc:
            if getattr(exc, "resp", None) is not None and exc.resp.status == 409:
                return service.events().get(calendarId=self.settings.google_calendar_id, eventId=event_id).execute()
            raise

    def update_event(self, event_id: str, start_at: str, end_at: str, timezone_name: str) -> dict:
        service = self._service()
        event = service.events().get(calendarId=self.settings.google_calendar_id, eventId=event_id).execute()
        event["start"] = {"dateTime": start_at, "timeZone": timezone_name}
        event["end"] = {"dateTime": end_at, "timeZone": timezone_name}
        return service.events().update(calendarId=self.settings.google_calendar_id, eventId=event_id, body=event, sendUpdates="all").execute()

    def cancel_event(self, event_id: str) -> None:
        try:
            self._service().events().delete(calendarId=self.settings.google_calendar_id, eventId=event_id, sendUpdates="all").execute()
        except HttpError as exc:
            if getattr(exc, "resp", None) is not None and exc.resp.status == 404:
                return
            raise

    def _credentials(self) -> Credentials:
        token_path = Path(self.settings.google_token_file)
        if not token_path.exists():
            raise CalendarUnavailable("Google Calendar is not connected; visit /api/google/connect first.")
        serialized = self.crypto.decrypt(token_path.read_text(encoding="utf-8"))
        credentials = Credentials.from_authorized_user_info(json.loads(serialized), SCOPES)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self._write_token(credentials.to_json())
        if not credentials.valid:
            raise CalendarUnavailable("Google Calendar authorization has expired; reconnect it.")
        return credentials

    def _write_token(self, serialized: str) -> None:
        token_path = Path(self.settings.google_token_file)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = token_path.with_name(f".{token_path.name}.{os.getpid()}.tmp")
        temporary.write_text(self.crypto.encrypt(serialized), encoding="utf-8")
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, token_path)

    def _service(self):
        return build("calendar", "v3", credentials=self._credentials(), cache_discovery=False)

    @staticmethod
    def _event_id(workspace_id: str, appointment_id: int) -> str:
        digest = hashlib.sha256(f"{workspace_id}:{appointment_id}".encode()).digest()[:15]
        # Google event IDs accept lower-case base32hex characters (0-9, a-v).
        return "ar" + base64.b32hexencode(digest).decode("ascii").lower().rstrip("=")
