from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, time, timedelta
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
        except Exception:  # noqa: BLE001 - Google auth/transport libraries expose several unrelated credential failure types.
            return False

    def free_slots(self, start_day, duration_minutes: int, count: int = 3) -> list[datetime]:
        if count <= 0:
            return []
        service = self._service()
        tz = ZoneInfo(self.settings.timezone)
        now = datetime.now(tz)
        window_start = datetime.combine(start_day, time.min, tzinfo=tz)
        window_end = datetime.combine(start_day + timedelta(days=21), time.min, tzinfo=tz)
        busy_response = service.freebusy().query(body={
            "timeMin": window_start.isoformat(), "timeMax": window_end.isoformat(), "timeZone": self.settings.timezone,
            "items": [{"id": self.settings.google_calendar_id}],
        }).execute()
        calendar_data = busy_response.get("calendars", {}).get(self.settings.google_calendar_id)
        if not isinstance(calendar_data, dict) or not isinstance(calendar_data.get("busy"), list):
            raise CalendarUnavailable("Google Calendar did not return valid availability; no slots were proposed.")
        if calendar_data.get("errors"):
            raise CalendarUnavailable(f"Google Calendar FreeBusy error: {calendar_data['errors']}")
        ranges = [
            (datetime.fromisoformat(item["start"]).astimezone(tz), datetime.fromisoformat(item["end"]).astimezone(tz))
            for item in calendar_data.get("busy", [])
        ]

        slots: list[datetime] = []
        for offset in range(21):
            day = start_day + timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            lower = datetime.combine(day, time(self.settings.business_hours_start), tzinfo=tz)
            upper = datetime.combine(day, time.min, tzinfo=tz) + timedelta(hours=self.settings.business_hours_end)
            if lower.date() == now.date() and lower < now:
                interval = self.settings.slot_interval_minutes
                minutes = ((now.minute + interval - 1) // interval) * interval
                lower = now.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minutes)
            if lower >= upper or upper <= now:
                continue
            candidate = lower
            while candidate + timedelta(minutes=duration_minutes) <= upper:
                end = candidate + timedelta(minutes=duration_minutes)
                if candidate >= now and not any(candidate < busy_end and end > busy_start for busy_start, busy_end in ranges):
                    slots.append(candidate)
                    if len(slots) == count:
                        return slots
                candidate += timedelta(minutes=self.settings.slot_interval_minutes)
        return slots

    def is_slot_available(self, start_at: datetime, end_at: datetime) -> bool:
        """Recheck one confirmed slot immediately before creating its event."""
        if start_at.utcoffset() is None or end_at.utcoffset() is None or end_at <= start_at:
            raise ValueError("Calendar availability requires a valid timezone-aware interval")
        response = self._service().freebusy().query(body={
            "timeMin": start_at.isoformat(),
            "timeMax": end_at.isoformat(),
            "timeZone": self.settings.timezone,
            "items": [{"id": self.settings.google_calendar_id}],
        }).execute()
        calendar_data = response.get("calendars", {}).get(self.settings.google_calendar_id) if isinstance(response, dict) else None
        if not isinstance(calendar_data, dict) or not isinstance(calendar_data.get("busy"), list):
            raise CalendarUnavailable("Google Calendar did not return valid availability; the appointment was not booked.")
        if calendar_data.get("errors"):
            raise CalendarUnavailable(f"Google Calendar FreeBusy error: {calendar_data['errors']}")
        for item in calendar_data["busy"]:
            try:
                busy_start = datetime.fromisoformat(item["start"])
                busy_end = datetime.fromisoformat(item["end"])
            except (KeyError, TypeError, ValueError) as exc:
                raise CalendarUnavailable("Google Calendar returned an invalid busy interval; the appointment was not booked.") from exc
            if busy_start.tzinfo is None or busy_end.tzinfo is None:
                raise CalendarUnavailable("Google Calendar returned a timezone-free busy interval; the appointment was not booked.")
            if start_at < busy_end and end_at > busy_start:
                return False
        return True

    def create_event(self, appointment: dict) -> dict:
        service = self._service()
        event_id = self._event_id(
            appointment["workspace_id"], appointment["id"], int(appointment.get("booking_attempt") or 1)
        )
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
                existing = self.find_appointment_event(appointment)
                if existing is None:
                    raise CalendarUnavailable("Google Calendar event ID already exists but is not an active matching appointment.") from exc
                return existing
            raise

    def find_appointment_event(self, appointment: dict) -> dict | None:
        """Verify whether this appointment's deterministic Google event already exists."""
        event_id = self._event_id(
            appointment["workspace_id"], appointment["id"], int(appointment.get("booking_attempt") or 1)
        )
        try:
            event = self._service().events().get(calendarId=self.settings.google_calendar_id, eventId=event_id).execute()
        except HttpError as exc:
            if getattr(exc, "resp", None) is not None and exc.resp.status == 404:
                return None
            raise CalendarUnavailable("Google Calendar could not verify the appointment event.") from exc
        if not isinstance(event, dict) or event.get("status") == "cancelled":
            return None
        if event.get("id") != event_id or event.get("status") != "confirmed":
            raise CalendarUnavailable("Google Calendar returned an event that cannot be safely reconciled.")

        extended = event.get("extendedProperties")
        private = extended.get("private") if isinstance(extended, dict) else None
        if not isinstance(private, dict):
            raise CalendarUnavailable("Google Calendar event is missing its Agenda Relay appointment marker.")
        if private.get("agendaRelayAppointmentId") != str(appointment["id"]):
            raise CalendarUnavailable("Google Calendar returned an event that does not match this appointment.")
        try:
            event_start = datetime.fromisoformat(event["start"]["dateTime"])
            event_end = datetime.fromisoformat(event["end"]["dateTime"])
            appointment_start = datetime.fromisoformat(appointment["start_at"])
            appointment_end = datetime.fromisoformat(appointment["end_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CalendarUnavailable("Google Calendar returned an incomplete appointment event.") from exc
        if (
            event_start.utcoffset() is None
            or event_end.utcoffset() is None
            or event_start != appointment_start
            or event_end != appointment_end
        ):
            raise CalendarUnavailable("Google Calendar event time does not match this appointment.")
        event_link = event.get("htmlLink")
        if event_link is not None and not isinstance(event_link, str):
            raise CalendarUnavailable("Google Calendar returned an invalid appointment link.")
        return {"id": event_id, "htmlLink": event_link}

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
    def _event_id(workspace_id: str, appointment_id: int, booking_attempt: int = 1) -> str:
        identity = f"{workspace_id}:{appointment_id}"
        if booking_attempt > 1:
            identity += f":{booking_attempt}"
        digest = hashlib.sha256(identity.encode()).digest()[:15]
        # Google event IDs accept lower-case base32hex characters (0-9, a-v).
        return "ar" + base64.b32hexencode(digest).decode("ascii").lower().rstrip("=")
