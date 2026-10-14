from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
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

    def process_payload(self, payload: Any) -> dict[str, int]:
        result = {
            "accepted": 0, "duplicates": 0, "proposals": 0, "confirmations": 0, "ignored": 0,
            "delivery_statuses": 0, "duplicate_statuses": 0, "rate_limited": 0, "retry_later": 0,
        }
        remaining_message_budget = self.settings.max_inbound_messages_per_webhook
        remaining_status_budget = 200
        if not isinstance(payload, dict):
            result["ignored"] += 1
            return result
        entries = payload.get("entry", [])
        if not isinstance(entries, list):
            result["ignored"] += 1
            return result
        for entry in entries:
            if not isinstance(entry, dict):
                result["ignored"] += 1
                continue
            changes = entry.get("changes", [])
            if not isinstance(changes, list):
                result["ignored"] += 1
                continue
            for change in changes:
                if not isinstance(change, dict):
                    result["ignored"] += 1
                    continue
                value = change.get("value", {})
                if not isinstance(value, dict):
                    result["ignored"] += 1
                    continue
                messages = value.get("messages", [])
                if messages is None:
                    messages = []
                elif not isinstance(messages, list):
                    result["ignored"] += 1
                    messages = []
                statuses = value.get("statuses", [])
                if statuses is None:
                    statuses = []
                elif not isinstance(statuses, list):
                    result["ignored"] += 1
                    statuses = []
                metadata = value.get("metadata", {})
                if (messages or statuses) and (
                    not isinstance(metadata, dict)
                    or str(metadata.get("phone_number_id", "")) != str(self.settings.whatsapp_phone_number_id)
                ):
                    result["ignored"] += len(messages) + len(statuses)
                    continue
                # Bound database work across the entire signed provider callback,
                # even when Meta batches multiple entries or changes together.
                statuses_to_process = statuses[:remaining_status_budget]
                remaining_status_budget -= len(statuses_to_process)
                for status_event in statuses_to_process:
                    parsed = self._parse_delivery_status(status_event)
                    if parsed is None:
                        result["ignored"] += 1
                        continue
                    message_id, status, provider_timestamp, error_code = parsed
                    inserted = self.store.record_whatsapp_delivery_status(
                        self.settings.workspace_id, message_id, status, provider_timestamp, error_code,
                    )
                    result["delivery_statuses" if inserted else "duplicate_statuses"] += 1
                result["ignored"] += len(statuses) - len(statuses_to_process)
                contacts = value.get("contacts", [])
                names = {}
                if isinstance(contacts, list):
                    for item in contacts[:200]:
                        if not isinstance(item, dict):
                            continue
                        profile = item.get("profile", {})
                        if isinstance(profile, dict) and isinstance(item.get("wa_id"), str):
                            name = profile.get("name")
                            names[item["wa_id"]] = name if isinstance(name, str) else None
                messages_to_process = messages[:remaining_message_budget]
                remaining_message_budget -= len(messages_to_process)
                result["ignored"] += len(messages) - len(messages_to_process)
                for message in messages_to_process:
                    if not isinstance(message, dict):
                        result["ignored"] += 1
                        continue
                    if message.get("type") != "text":
                        result["ignored"] += 1
                        continue
                    external_id, sender = message.get("id"), message.get("from")
                    text = message.get("text", {})
                    body = text.get("body", "") if isinstance(text, dict) else ""
                    if (
                        not isinstance(external_id, str) or not external_id.strip()
                        or not isinstance(sender, str) or not sender.strip()
                        or not isinstance(body, str) or not body.strip()
                        or len(external_id) > 256
                        or len(sender) > 64
                    ):
                        result["ignored"] += 1
                        continue
                    body = body.strip()
                    if len(body) > self.settings.max_inbound_message_chars:
                        result["ignored"] += 1
                        continue
                    received_at = self._message_time(message)
                    ingest_status = self.store.accept_inbound_message(
                        self.settings.workspace_id,
                        external_id,
                        sender,
                        body,
                        received_at,
                        max_per_sender=self.settings.max_inbound_per_contact_per_hour,
                        max_total=self.settings.max_inbound_total_per_hour,
                    )
                    if ingest_status == "duplicate":
                        result["duplicates"] += 1
                        continue
                    if ingest_status == "in_progress":
                        result["duplicates"] += 1
                        result["retry_later"] += 1
                        continue
                    if ingest_status == "rate_limited":
                        result["rate_limited"] += 1
                        continue
                    if ingest_status == "accepted":
                        result["accepted"] += 1
                    else:
                        result["duplicates"] += 1
                        try:
                            stored_body = self.store.inbound_message_body(self.settings.workspace_id, external_id)
                        except Exception:
                            self.store.retry_inbound_message(self.settings.workspace_id, external_id)
                            raise
                        if stored_body is None:
                            self.store.retry_inbound_message(self.settings.workspace_id, external_id)
                            result["retry_later"] += 1
                            continue
                        body = stored_body
                    try:
                        self._process_inbound_message(sender, external_id, body, names.get(sender), result)
                    except Exception:
                        self.store.retry_inbound_message(self.settings.workspace_id, external_id)
                        raise
                    else:
                        self.store.complete_inbound_message(self.settings.workspace_id, external_id)
        return result

    def _process_inbound_message(self, sender: str, external_id: str, body: str, display_name: str | None, result: dict[str, int]) -> None:
        if self.is_paused():
            self.store.audit(self.settings.workspace_id, "scheduler", "automation.skipped_paused", "message", external_id, {})
            return
        contact_id = self.store.upsert_contact(
            self.settings.workspace_id, sender, self.settings.timezone, display_name=display_name,
        )
        proposal_cutoff = (utc_now() - timedelta(hours=self.settings.booking_link_ttl_hours)).isoformat()
        active = self.store.latest_sent_proposal(self.settings.workspace_id, sender, proposal_cutoff)
        if active:
            selected = confirmation_index(body, len(active["slots"]))
            if selected is not None:
                appointment_id = self.store.confirm_proposal(self.settings.workspace_id, active["id"], selected, "contact")
                result["confirmations"] += 1
                if self.settings.auto_book_confirmed:
                    self.book_appointment(appointment_id, actor="automation")
                return
        local_today = datetime.now(ZoneInfo(self.settings.timezone)).date()
        intent = self.intent_provider.analyse(body, local_today, self.settings.default_duration_minutes)
        if not intent.is_scheduling:
            result["ignored"] += 1
            return
        existing_request = self.store.request_for_source_message(self.settings.workspace_id, external_id)
        if existing_request:
            if existing_request["proposal_id"] or existing_request["status"] != "detected":
                return
            request_id = int(existing_request["id"])
        else:
            request_id = self.store.update_contact_and_create_request(
                self.settings.workspace_id, contact_id, intent.language, display_name,
                external_id, intent.title, intent.duration_minutes, self.settings.timezone,
                intent.requested_start.isoformat(), intent.confidence,
            )
        contact = self.store.get_contact(self.settings.workspace_id, contact_id) or {}
        try:
            slots = self.calendar.free_slots(
                intent.requested_start, intent.duration_minutes, preferred_time=intent.preferred_time,
            )
        except Exception as exc:  # noqa: BLE001 - Google provider SDK errors are not a stable shared exception type.
            self.store.transition_request(self.settings.workspace_id, request_id, "failed", "scheduler", {"provider": "google_calendar", "error": str(exc)[:200]})
            return
        if not slots:
            self.store.transition_request(self.settings.workspace_id, request_id, "needs_clarification", "scheduler", {"reason": "no_slots_in_search_window"})
            return
        token = secrets.token_urlsafe(32)
        reply = self._proposal_reply(intent.language, slots, token, contact.get("timezone") or self.settings.timezone)
        proposal_id, _ = self.store.create_proposal(self.settings.workspace_id, request_id, reply, [slot.isoformat() for slot in slots], token)
        result["proposals"] += 1
        if self.settings.auto_send_suggestions:
            self.send_proposal(proposal_id, actor="automation")

    def create_assisted_proposal(self, message_text: str) -> int:
        """Create a manual-only personal WhatsApp proposal without retaining pasted text."""
        text = message_text.strip()
        if not text or len(text) > 5000:
            raise ValueError("Paste a message between 1 and 5,000 characters.")
        local_today = datetime.now(ZoneInfo(self.settings.timezone)).date()
        intent = self.intent_provider.analyse(text, local_today, self.settings.default_duration_minutes)
        if not intent.is_scheduling:
            raise ValueError("I could not identify a scheduling request. Review the message and try again.")
        if not self.calendar.connected():
            raise RuntimeError("Google Calendar is not connected. Connect it before checking availability.")
        # The identifier is deliberately synthetic: there is no personal WhatsApp API
        # identity or phone number available, and neither is needed for the booking link.
        sender = f"assisted:{secrets.token_urlsafe(18)}"
        source_id = f"assisted:{secrets.token_urlsafe(18)}"
        _, request_id = self.store.create_contact_request(
            self.settings.workspace_id, sender, self.settings.timezone, intent.language,
            "Personal WhatsApp (manual)", source_id, intent.title, intent.duration_minutes,
            intent.requested_start.isoformat(), intent.confidence,
        )
        try:
            slots = self.calendar.free_slots(
                intent.requested_start, intent.duration_minutes, preferred_time=intent.preferred_time,
            )
        except Exception as exc:  # Calendar transport/auth failures vary by provider library; persist the request failure.
            self.store.transition_request(
                self.settings.workspace_id, request_id, "failed", "assisted_personal",
                {"provider": "google_calendar", "error": str(exc)[:200]},
            )
            raise
        if not slots:
            self.store.transition_request(
                self.settings.workspace_id, request_id, "needs_clarification", "assisted_personal",
                {"reason": "no_slots_in_search_window"},
            )
            raise ValueError("No suitable times were found in the next three weeks. Try a broader date or check your calendar settings.")
        token = secrets.token_urlsafe(32)
        reply = self._assisted_proposal_reply(intent.language, slots, token, self.settings.timezone)
        proposal_id, _ = self.store.create_proposal(
            self.settings.workspace_id, request_id, reply, [slot.isoformat() for slot in slots], token,
        )
        self.store.audit(
            self.settings.workspace_id, "assisted_personal", "proposal.prepared_for_manual_share",
            "proposal", proposal_id, {"text_retained": False, "source": "operator_paste"},
        )
        return proposal_id

    def send_proposal(self, proposal_id: int, actor: str = "operator") -> dict:
        if self.is_paused():
            raise RuntimeError("Automation is paused; resume it before sending")
        proposal = self.store.get_proposal(self.settings.workspace_id, proposal_id)
        if not proposal:
            raise KeyError("Proposal not found")
        if proposal["sender"].startswith("assisted:"):
            raise ValueError("Personal WhatsApp proposals are manual-only and cannot be sent through the Business API.")
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
            self.store.mark_proposal_sent(self.settings.workspace_id, proposal_id, provider_id, actor)
            self.store.audit(self.settings.workspace_id, actor, "proposal.sent", "proposal", proposal_id, {"provider_message_id": provider_id})
            return {"status": "sent", "provider_message_id": provider_id}
        except WhatsAppUnavailable as exc:
            if exc.retry_safe:
                self.store.mark_proposal_failed(self.settings.workspace_id, proposal_id, str(exc))
            else:
                self.store.mark_proposal_manual_required(self.settings.workspace_id, proposal_id, str(exc))
            raise
        except Exception as exc:  # Provider send errors vary; persist ambiguous delivery for manual review, not retry.
            self.store.mark_proposal_manual_required(self.settings.workspace_id, proposal_id, str(exc))
            raise

    def confirm_public(self, token: str, slot_index: int, consent: bool) -> dict[str, Any]:
        proposal = self.public_proposal(token)
        if not consent:
            raise ValueError("Consent is required before confirming a slot")
        if slot_index < 0 or slot_index >= len(proposal["slots"]):
            raise ValueError("Selected slot is outside proposal")
        if self.settings.auto_book_confirmed and not self.is_paused():
            start_at = datetime.fromisoformat(proposal["slots"][slot_index])
            end_at = start_at + timedelta(minutes=int(proposal["duration_minutes"]))
            if not self.calendar.is_slot_available(start_at, end_at):
                raise CalendarUnavailable(
                    "That time has just become unavailable. Please choose another of the proposed times."
                )
        self.store.update_contact(
            proposal["workspace_id"], proposal["contact_id"], display_name=proposal.get("display_name"),
            email=proposal.get("email"), timezone_name=proposal.get("contact_timezone") or self.settings.timezone, language=proposal.get("language", "en"),
            consent_status="confirmed",
        )
        appointment_id = self.store.confirm_proposal(proposal["workspace_id"], proposal["id"], slot_index, "booking_link")
        booking_result = None
        if self.settings.auto_book_confirmed and not self.is_paused():
            booking_result = self.book_appointment(appointment_id, actor="automation")
        return {
            "appointment_id": appointment_id,
            "booked": bool(booking_result and booking_result.get("status") == "booked"),
            "warning": booking_result.get("warning") if booking_result else None,
        }

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
        appointment = self.store.claim_booking(self.settings.workspace_id, appointment_id, actor)
        if not appointment:
            existing = self.store.get_appointment(self.settings.workspace_id, appointment_id)
            if existing and existing["status"] == "booked":
                self._ensure_booking_reminder(existing)
                return {"status": "booked", "idempotent": True, "event_link": existing.get("google_event_link")}
            raise ValueError("Appointment is not ready to book")
        if appointment["consent_status"] == "revoked":
            self.store.mark_booking_failed(self.settings.workspace_id, appointment_id, "Contact consent is revoked", actor, {"reason": "consent_revoked"})
            raise ValueError("Contact consent is revoked")
        try:
            if not self.calendar.is_slot_available(
                datetime.fromisoformat(appointment["start_at"]),
                datetime.fromisoformat(appointment["end_at"]),
            ):
                raise CalendarUnavailable(
                    "The selected time has since become busy. No calendar event was created; review the request and offer new times."
                )
        except Exception as exc:
            self.store.mark_booking_failed(self.settings.workspace_id, appointment_id, str(exc), actor, {"error": str(exc)[:200]})
            raise

        try:
            event = self.calendar.create_event(appointment)
        except Exception as exc:
            # A provider timeout can happen after Google accepted the insert.
            # Do not make the appointment immediately retryable: reconcile the
            # deterministic event ID before another external create attempt.
            self.store.mark_booking_manual_required(
                self.settings.workspace_id, appointment_id, "calendar_create_result_unknown", actor
            )
            raise CalendarUnavailable(
                "Google Calendar may have accepted this event. Verify Calendar before retrying the booking."
            ) from exc

        try:
            self.store.mark_booked(self.settings.workspace_id, appointment_id, event["id"], event.get("htmlLink"))
        except Exception as exc:
            current = self.store.get_appointment(self.settings.workspace_id, appointment_id)
            if current and current["status"] == "booked":
                # The commit may have succeeded before its acknowledgement was
                # lost; continue from the durable state rather than retrying it.
                event = {"id": current["google_event_id"], "htmlLink": current.get("google_event_link")}
            else:
                self.store.mark_booking_manual_required(
                    self.settings.workspace_id, appointment_id, "booking_state_persist_failed", actor
                )
                raise CalendarUnavailable(
                    "Google Calendar event was created, but local booking state needs reconciliation before retrying."
                ) from exc

        warning = None
        if appointment["sender"].startswith("assisted:"):
            warning = "Appointment booked in Google Calendar. Send the WhatsApp confirmation draft manually."
            self.store.audit(
                self.settings.workspace_id, actor, "confirmation.manual_required", "appointment", appointment_id,
                {"channel": "personal_whatsapp", "automatic_send": False},
            )
        else:
            try:
                self._send_booking_confirmation(appointment)
            except Exception as exc:  # noqa: BLE001 - WhatsApp send can fail after booking; preserve the booked state and manual warning.
                warning = "Calendar event was booked, but WhatsApp confirmation requires operator attention."
                self.store.audit(self.settings.workspace_id, actor, "confirmation.send_failed", "appointment", appointment_id, {"error": str(exc)[:200]})
        self._ensure_booking_reminder(appointment)
        self.store.audit(self.settings.workspace_id, actor, "appointment.booked", "appointment", appointment_id, {"google_event_id": event["id"], "warning": warning})
        return {"status": "booked", "event_link": event.get("htmlLink"), "warning": warning}

    def _ensure_booking_reminder(self, appointment: dict) -> None:
        if appointment["sender"].startswith("assisted:"):
            return
        reminder_at = datetime.fromisoformat(appointment["start_at"]).astimezone(UTC) - timedelta(
            minutes=self.settings.reminder_minutes_before
        )
        if reminder_at <= utc_now():
            return
        self.store.schedule_job(
            self.settings.workspace_id,
            "appointment_reminder",
            f"reminder:{appointment['id']}:{self.settings.reminder_minutes_before}",
            reminder_at.isoformat(),
            {"appointment_id": appointment["id"]},
        )

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

    def reconcile_stale_booking(self, appointment_id: int, actor: str = "operator") -> dict[str, Any]:
        appointment = self.store.get_appointment(self.settings.workspace_id, appointment_id)
        if not appointment:
            raise KeyError("Appointment not found")
        if appointment["status"] != "manual_required":
            raise ValueError("Appointment is not awaiting calendar reconciliation")

        event = self.calendar.find_appointment_event(appointment)
        outcome = self.store.reconcile_stale_booking(self.settings.workspace_id, appointment_id, event, actor)
        if outcome == "event_not_found":
            return {
                "status": "failed",
                "retryable": True,
                "warning": "No matching Google Calendar event was found. Review the request, then explicitly retry booking if appropriate.",
            }

        reminder_at = datetime.fromisoformat(appointment["start_at"]).astimezone(UTC) - timedelta(minutes=self.settings.reminder_minutes_before)
        if reminder_at > utc_now() and not appointment["sender"].startswith("assisted:"):
            self.store.schedule_job(
                self.settings.workspace_id, "appointment_reminder", f"reminder:{appointment_id}:{self.settings.reminder_minutes_before}",
                reminder_at.isoformat(), {"appointment_id": appointment_id},
            )
        return {
            "status": "booked",
            "event_link": event.get("htmlLink") if event else None,
            "warning": "Google Calendar confirms the event. No WhatsApp confirmation was sent during recovery; follow up manually.",
        }

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
        self.store.purge_expired(self.settings.workspace_id, self.settings.data_retention_days)
        totals["scheduling_records_deleted"] = sum(
            self.store.purge_terminal_scheduling_records(
                self.settings.workspace_id, self.settings.scheduling_retention_days,
                self.settings.booking_link_ttl_hours,
            ).values()
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
            except Exception as exc:  # noqa: BLE001 - provider timeouts are operationally ambiguous; do not auto-retry reminders.
                # Provider timeouts are operationally ambiguous: do not auto-retry or risk duplicate reminders.
                self.store.complete_job(self.settings.workspace_id, job["id"], "manual_required", str(exc)[:500])
                totals["manual_required"] += 1
        return totals

    def readiness(self) -> dict[str, Any]:
        errors, warnings = self.settings.validation()
        google_connected = bool(getattr(self.calendar, "connected", lambda: False)())
        whatsapp_configured = bool(getattr(self.whatsapp, "configured", lambda: False)())
        whatsapp_ready = not self.settings.whatsapp_cloud_api_enabled or whatsapp_configured
        providers = {
            "google_calendar": {"ready": google_connected, "detail": "Connected" if google_connected else "OAuth connection required"},
            "whatsapp": {
                "ready": whatsapp_ready,
                "enabled": self.settings.whatsapp_cloud_api_enabled,
                "detail": ("Configured" if whatsapp_configured else "Cloud API credentials required") if self.settings.whatsapp_cloud_api_enabled else "Disabled; personal WhatsApp assisted mode",
            },
        }
        can_resume = not errors and google_connected and whatsapp_ready
        paused = self.is_paused()
        ingress_ready = self.settings.is_production and not errors and whatsapp_ready and (google_connected or paused)
        if ingress_ready:
            ingress_detail = "Production ingress is valid" if self.settings.whatsapp_cloud_api_enabled else "Production HTTPS booking links are valid; WhatsApp Cloud API is disabled"
        elif not self.settings.is_production:
            ingress_detail = "APP_ENV=production is required before public exposure"
        elif errors:
            ingress_detail = "Production configuration errors must be resolved before public exposure"
        elif not whatsapp_ready:
            ingress_detail = "WhatsApp Cloud API credentials are required before public exposure"
        else:
            ingress_detail = "Connect Google Calendar or pause automation before public OAuth bootstrap"
        ready = can_resume and not paused
        return {
            "ready": ready, "can_resume": can_resume, "mode": self.settings.app_env, "automation_paused": paused,
            "providers": providers, "errors": errors, "warnings": warnings,
            "public_ingress": {
                "ready": ingress_ready,
                "detail": ingress_detail,
            },
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

    def _assisted_proposal_reply(self, language: str, slots: list[datetime], token: str, timezone_name: str) -> str:
        target_timezone = ZoneInfo(timezone_name)
        rendered = [self._format_slot(slot.astimezone(target_timezone), language, index + 1) for index, slot in enumerate(slots)]
        link = f"{self.settings.public_base_url}/book/{token}"
        if language == "nl":
            return "Ik kan deze momenten aanbieden:\n" + "\n".join(rendered) + f"\n\nTijdzone: {timezone_name}. Kies een moment via deze boekingspagina: {link}"
        return "I can offer these times:\n" + "\n".join(rendered) + f"\n\nTime zone: {timezone_name}. Please choose a time on this booking page: {link}"

    @staticmethod
    def _format_slot(slot: datetime, language: str, number: int) -> str:
        if language == "nl":
            days = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
            return f"{number}. {days[slot.weekday()]} {slot.day}-{slot.month} om {slot:%H:%M}"
        return f"{number}. {slot:%A} {slot.day} {slot:%B} at {slot:%H:%M}"

    def _send_booking_confirmation(self, appointment: dict) -> None:
        if appointment["sender"].startswith("assisted:"):
            raise RuntimeError("Personal WhatsApp confirmations must be sent manually by the operator.")
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
            return datetime.fromtimestamp(int(message.get("timestamp")), tz=UTC).isoformat()
        except (TypeError, ValueError, OverflowError, OSError):
            return utc_now().isoformat()

    @staticmethod
    def _parse_delivery_status(event: Any) -> tuple[str, str, str, str | None] | None:
        if not isinstance(event, dict):
            return None
        message_id = event.get("id")
        status = event.get("status")
        raw_timestamp = event.get("timestamp")
        if (
            not isinstance(message_id, str) or not message_id.strip() or len(message_id) > 255
            or not isinstance(status, str) or status not in {"sent", "delivered", "read", "failed", "deleted"}
            or isinstance(raw_timestamp, bool) or not isinstance(raw_timestamp, (str, int))
        ):
            return None
        timestamp_text = str(raw_timestamp)
        if not timestamp_text.isdigit() or len(timestamp_text) > 12:
            return None
        try:
            provider_timestamp = datetime.fromtimestamp(int(timestamp_text), tz=UTC).isoformat()
        except (ValueError, OverflowError, OSError):
            return None
        error_code = None
        errors = event.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            raw_code = errors[0].get("code")
            if isinstance(raw_code, int) and not isinstance(raw_code, bool):
                raw_code = str(raw_code)
            if isinstance(raw_code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", raw_code):
                error_code = raw_code
        return message_id.strip(), status, provider_timestamp, error_code
