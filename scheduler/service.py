from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .calendar import CalendarUnavailable
from .config import Settings
from .intent import DEFAULT_PROVIDER, IntentProvider, confirmation_index
from .store import Store, utc_now
from .whatsapp import WhatsAppUnavailable


class SchedulingService:
    def __init__(self, settings: Settings, store: Store, calendar, whatsapp, intent_provider: IntentProvider | None = None):
        self.settings = settings
        self.store = store
        self.calendar = calendar
        self.whatsapp = whatsapp
        self.intent_provider = intent_provider or DEFAULT_PROVIDER

    def process_payload(self, payload: dict) -> dict[str, int]:
        result = {"accepted": 0, "duplicates": 0, "proposals": 0, "confirmations": 0, "ignored": 0}
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                names = {item.get("wa_id"): item.get("profile", {}).get("name") for item in value.get("contacts", [])}
                for message in value.get("messages", []):
                    if message.get("type") != "text":
                        result["ignored"] += 1
                        continue
                    external_id, sender = message.get("id"), message.get("from")
                    body = message.get("text", {}).get("body", "").strip()
                    if not external_id or not sender or not body:
                        result["ignored"] += 1
                        continue
                    received_at = self._message_time(message)
                    if not self.store.record_inbound(self.settings.workspace_id, external_id, sender, body, received_at):
                        result["duplicates"] += 1
                        continue
                    result["accepted"] += 1
                    if self.is_paused():
                        self.store.audit(self.settings.workspace_id, "scheduler", "automation.skipped_paused", "message", external_id, {})
                        continue
                    contact_id = self.store.upsert_contact(self.settings.workspace_id, sender, self.settings.timezone, display_name=names.get(sender))
                    proposal_cutoff = (utc_now() - timedelta(hours=self.settings.booking_link_ttl_hours)).isoformat()
                    active = self.store.latest_sent_proposal(self.settings.workspace_id, sender, proposal_cutoff)
                    if active:
                        selected = confirmation_index(body, len(active["slots"]))
                        if selected is not None:
                            appointment_id = self.store.confirm_proposal(self.settings.workspace_id, active["id"], selected, "contact")
                            result["confirmations"] += 1
                            if self.settings.auto_book_confirmed:
                                self.book_appointment(appointment_id, actor="automation")
                            continue
                    history = "\n".join(item["body"] for item in self.store.recent_messages(self.settings.workspace_id, sender))
                    local_today = datetime.now(ZoneInfo(self.settings.timezone)).date()
                    intent = self.intent_provider.analyse(history, local_today, self.settings.default_duration_minutes)
                    if not intent.is_scheduling:
                        result["ignored"] += 1
                        continue
                    contact_id = self.store.upsert_contact(self.settings.workspace_id, sender, self.settings.timezone, intent.language, names.get(sender))
                    contact = self.store.get_contact(self.settings.workspace_id, contact_id) or {}
                    request_id = self.store.create_request(
                        self.settings.workspace_id, contact_id, external_id, intent.title, intent.duration_minutes,
                        self.settings.timezone, intent.requested_start.isoformat(), intent.confidence,
                    )
                    try:
                        slots = self.calendar.free_slots(intent.requested_start, intent.duration_minutes)
                    except Exception as exc:
                        self.store.transition_request(self.settings.workspace_id, request_id, "failed", "scheduler", {"provider": "google_calendar", "error": str(exc)[:200]})
                        continue
                    if not slots:
                        self.store.transition_request(self.settings.workspace_id, request_id, "needs_clarification", "scheduler", {"reason": "no_slots_in_search_window"})
                        continue
                    token = secrets.token_urlsafe(32)
                    reply = self._proposal_reply(intent.language, slots, token, contact.get("timezone") or self.settings.timezone)
                    proposal_id, _ = self.store.create_proposal(self.settings.workspace_id, request_id, reply, [slot.isoformat() for slot in slots], token)
                    result["proposals"] += 1
                    if self.settings.auto_send_suggestions:
                        self.send_proposal(proposal_id, actor="automation")
        return result

    def send_proposal(self, proposal_id: int, actor: str = "operator") -> dict:
        if self.is_paused():
            raise RuntimeError("Automation is paused; resume it before sending")
        proposal = self.store.get_proposal(self.settings.workspace_id, proposal_id)
        if not proposal:
            raise KeyError("Proposal not found")
        if proposal["status"] not in {"pending_approval", "send_failed"}:
            raise ValueError("Proposal is no longer sendable")
        if proposal["consent_status"] == "revoked":
            raise ValueError("Contact consent is revoked")
        self._enforce_rate_limit(proposal["sender"])
        if not self.store.claim_proposal_send(self.settings.workspace_id, proposal_id):
            raise ValueError("Proposal is already being sent or is no longer sendable")
        try:
            response = self.whatsapp.send_reply(proposal["sender"], proposal["reply_text"], None)
            provider_id = response.get("messages", [{}])[0].get("id")
            self.store.mark_proposal_sent(self.settings.workspace_id, proposal_id, provider_id)
            self.store.audit(self.settings.workspace_id, actor, "proposal.sent", "proposal", proposal_id, {"provider_message_id": provider_id})
            return {"status": "sent", "provider_message_id": provider_id}
        except WhatsAppUnavailable as exc:
            if exc.retry_safe:
                self.store.mark_proposal_failed(self.settings.workspace_id, proposal_id, str(exc))
            else:
                self.store.mark_proposal_manual_required(self.settings.workspace_id, proposal_id, str(exc))
            raise
        except Exception as exc:
            self.store.mark_proposal_manual_required(self.settings.workspace_id, proposal_id, str(exc))
            raise

    def confirm_public(self, token: str, slot_index: int, consent: bool) -> int:
        proposal = self.public_proposal(token)
        if not consent:
            raise ValueError("Consent is required before confirming a slot")
        self.store.update_contact(
            proposal["workspace_id"], proposal["contact_id"], display_name=proposal.get("display_name"),
            email=proposal.get("email"), timezone_name=proposal.get("contact_timezone") or self.settings.timezone, language=proposal.get("language", "en"),
            consent_status="confirmed",
        )
        appointment_id = self.store.confirm_proposal(proposal["workspace_id"], proposal["id"], slot_index, "booking_link")
        if self.settings.auto_book_confirmed and not self.is_paused():
            self.book_appointment(appointment_id, actor="automation")
        return appointment_id

    def public_proposal(self, token: str) -> dict:
        proposal = self.store.get_proposal_by_token(token)
        if not proposal or proposal["status"] != "sent":
            raise KeyError("Booking link not found")
        activated_at = datetime.fromisoformat(proposal.get("sent_at") or proposal["created_at"])
        if activated_at + timedelta(hours=self.settings.booking_link_ttl_hours) <= utc_now():
            raise ValueError("This booking link has expired; ask for new time suggestions")
        if proposal["consent_status"] == "revoked":
            raise ValueError("This contact has revoked consent")
        return proposal

    def book_appointment(self, appointment_id: int, actor: str = "operator") -> dict[str, Any]:
        if self.is_paused():
            raise RuntimeError("Automation is paused; external calendar changes are disabled")
        appointment = self.store.claim_booking(self.settings.workspace_id, appointment_id)
        if not appointment:
            existing = self.store.get_appointment(self.settings.workspace_id, appointment_id)
            if existing and existing["status"] == "booked":
                return {"status": "booked", "idempotent": True, "event_link": existing.get("google_event_link")}
            raise ValueError("Appointment is not ready to book")
        if appointment["consent_status"] == "revoked":
            self.store.mark_booking_failed(self.settings.workspace_id, appointment_id, "Contact consent is revoked")
            self.store.transition_request(self.settings.workspace_id, appointment["request_id"], "failed", actor, {"reason": "consent_revoked"})
            raise ValueError("Contact consent is revoked")
        try:
            event = self.calendar.create_event(appointment)
            self.store.mark_booked(self.settings.workspace_id, appointment_id, event["id"], event.get("htmlLink"))
        except Exception as exc:
            self.store.mark_booking_failed(self.settings.workspace_id, appointment_id, str(exc))
            self.store.transition_request(self.settings.workspace_id, appointment["request_id"], "failed", actor, {"error": str(exc)[:200]})
            raise

        warning = None
        try:
            self._send_booking_confirmation(appointment)
        except Exception as exc:
            warning = "Calendar event was booked, but WhatsApp confirmation requires operator attention."
            self.store.audit(self.settings.workspace_id, actor, "confirmation.send_failed", "appointment", appointment_id, {"error": str(exc)[:200]})
        reminder_at = datetime.fromisoformat(appointment["start_at"]).astimezone(timezone.utc) - timedelta(minutes=self.settings.reminder_minutes_before)
        if reminder_at > utc_now():
            self.store.schedule_job(
                self.settings.workspace_id, "appointment_reminder", f"reminder:{appointment_id}:{self.settings.reminder_minutes_before}",
                reminder_at.isoformat(), {"appointment_id": appointment_id},
            )
        self.store.audit(self.settings.workspace_id, actor, "appointment.booked", "appointment", appointment_id, {"google_event_id": event["id"], "warning": warning})
        return {"status": "booked", "event_link": event.get("htmlLink"), "warning": warning}

    def cancel_appointment(self, appointment_id: int, actor: str = "operator") -> dict:
        if self.is_paused():
            raise RuntimeError("Automation is paused; external calendar changes are disabled")
        appointment = self.store.get_appointment(self.settings.workspace_id, appointment_id)
        if not appointment:
            raise KeyError("Appointment not found")
        if appointment.get("google_event_id"):
            self.calendar.cancel_event(appointment["google_event_id"])
        changed = self.store.cancel_appointment(self.settings.workspace_id, appointment_id, actor)
        return {"status": "cancelled", "changed": changed}

    def run_due_jobs(self, limit: int = 20) -> dict[str, int]:
        totals = {"claimed": 0, "sent": 0, "manual_required": 0, "failed": 0, "recovered": 0, "recovered_sends": 0, "recovered_bookings": 0, "expired": 0}
        totals["recovered"] = self.store.recover_stale_jobs(
            self.settings.workspace_id, (utc_now() - timedelta(minutes=15)).isoformat()
        )
        totals["recovered_sends"] = self.store.recover_stale_proposal_sends(
            self.settings.workspace_id, (utc_now() - timedelta(minutes=15)).isoformat()
        )
        totals["recovered_bookings"] = self.store.recover_stale_bookings(
            self.settings.workspace_id, (utc_now() - timedelta(minutes=15)).isoformat()
        )
        totals["expired"] = self.store.expire_stale_proposals(
            self.settings.workspace_id, (utc_now() - timedelta(hours=self.settings.booking_link_ttl_hours)).isoformat()
        )
        if self.is_paused():
            return totals
        for job in self.store.claim_due_jobs(self.settings.workspace_id, utc_now().isoformat(), limit):
            totals["claimed"] += 1
            try:
                if job["job_type"] != "appointment_reminder":
                    self.store.complete_job(self.settings.workspace_id, job["id"], "failed", "Unknown job type")
                    totals["failed"] += 1
                    continue
                appointment = self.store.get_appointment(self.settings.workspace_id, int(job["payload"]["appointment_id"]))
                if not appointment or appointment["status"] != "booked":
                    self.store.complete_job(self.settings.workspace_id, job["id"], "cancelled")
                    continue
                if not self.settings.whatsapp_reminder_template:
                    self.store.complete_job(self.settings.workspace_id, job["id"], "manual_required", "No approved WhatsApp reminder template configured")
                    totals["manual_required"] += 1
                    continue
                self._enforce_rate_limit(appointment["sender"])
                display_timezone = appointment.get("contact_timezone") or appointment["timezone"]
                local = datetime.fromisoformat(appointment["start_at"]).astimezone(ZoneInfo(display_timezone))
                self.whatsapp.send_template(appointment["sender"], self.settings.whatsapp_reminder_template, appointment["language"], [appointment["title"], local.strftime("%d-%m-%Y %H:%M")])
                self.store.complete_job(self.settings.workspace_id, job["id"], "sent")
                totals["sent"] += 1
            except Exception as exc:
                # Provider timeouts are operationally ambiguous: do not auto-retry or risk duplicate reminders.
                self.store.complete_job(self.settings.workspace_id, job["id"], "manual_required", str(exc)[:500])
                totals["manual_required"] += 1
        self.store.purge_expired(self.settings.workspace_id, self.settings.data_retention_days)
        return totals

    def readiness(self) -> dict[str, Any]:
        errors, warnings = self.settings.validation()
        google_connected = bool(getattr(self.calendar, "connected", lambda: False)())
        whatsapp_configured = bool(getattr(self.whatsapp, "configured", lambda: False)())
        providers = {
            "google_calendar": {"ready": google_connected, "detail": "Connected" if google_connected else "OAuth connection required"},
            "whatsapp": {"ready": whatsapp_configured, "detail": "Configured" if whatsapp_configured else "Cloud API credentials required"},
        }
        ready = not errors and all(item["ready"] for item in providers.values()) and not self.is_paused()
        return {
            "ready": ready, "mode": self.settings.app_env, "automation_paused": self.is_paused(),
            "providers": providers, "errors": errors, "warnings": warnings,
            "storage_encrypted": bool(self.settings.data_encryption_key),
            "integrations": {
                "hai": {
                    "enabled": self.settings.hai_connector_enabled,
                    "mode": "local_read_only_metadata" if self.settings.hai_connector_enabled else "disabled",
                }
            },
        }

    def is_paused(self) -> bool:
        default = "true" if self.settings.automation_paused else "false"
        return self.store.get_state(self.settings.workspace_id, "automation_paused", default) == "true"

    def _proposal_reply(self, language: str, slots: list[datetime], token: str, timezone_name: str) -> str:
        target_timezone = ZoneInfo(timezone_name)
        rendered = [self._format_slot(slot.astimezone(target_timezone), language, index + 1) for index, slot in enumerate(slots)]
        link = f"{self.settings.public_base_url}/book/{token}"
        if language == "nl":
            return "Ik kan deze momenten aanbieden:\n" + "\n".join(rendered) + f"\n\nTijdzone: {timezone_name}. Antwoord met 1, 2 of 3, of kies via {link}"
        return "I can offer these times:\n" + "\n".join(rendered) + f"\n\nTime zone: {timezone_name}. Reply with 1, 2 or 3, or choose at {link}"

    @staticmethod
    def _format_slot(slot: datetime, language: str, number: int) -> str:
        if language == "nl":
            days = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
            return f"{number}. {days[slot.weekday()]} {slot.day}-{slot.month} om {slot:%H:%M}"
        return f"{number}. {slot:%A} {slot.day} {slot:%B} at {slot:%H:%M}"

    def _send_booking_confirmation(self, appointment: dict) -> None:
        self._enforce_rate_limit(appointment["sender"])
        display_timezone = appointment.get("contact_timezone") or appointment["timezone"]
        local = datetime.fromisoformat(appointment["start_at"]).astimezone(ZoneInfo(display_timezone))
        if appointment["language"] == "nl":
            text = f"Bevestigd: {appointment['title']} op {local:%d-%m-%Y} om {local:%H:%M} ({display_timezone})."
        else:
            text = f"Confirmed: {appointment['title']} on {local:%d-%m-%Y} at {local:%H:%M} ({display_timezone})."
        self.whatsapp.send_reply(appointment["sender"], text)

    def _enforce_rate_limit(self, sender: str) -> None:
        if not self.store.reserve_rate_event(
            self.settings.workspace_id, sender, "whatsapp.outbound", self.settings.max_outbound_per_contact_per_hour, 60
        ):
            raise RuntimeError("Outbound WhatsApp rate limit reached for this contact; retry later")

    @staticmethod
    def _message_time(message: dict) -> str:
        try:
            return datetime.fromtimestamp(int(message.get("timestamp")), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            return utc_now().isoformat()
