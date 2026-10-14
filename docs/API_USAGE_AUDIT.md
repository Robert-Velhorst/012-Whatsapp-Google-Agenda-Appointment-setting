# API usage audit

## Public/provider-facing

| Method/path | Caller | Purpose | Protection |
|---|---|---|---|
| `GET /webhook/whatsapp` | Meta | Verification challenge | Exact verify token; endpoint disabled when `WHATSAPP_CLOUD_API_ENABLED=false` |
| `POST /webhook/whatsapp` | Meta | Inbound messages and outbound delivery-status callbacks | HMAC, 1 MB limit, configured phone-number ID check; messages and each provider status are independently deduplicated; endpoint disabled when `WHATSAPP_CLOUD_API_ENABLED=false` |
| `GET /book/<token>` | Contact | View offered slots | 256-bit private token, no-store |
| `POST /book/<token>` | Contact | Confirm one slot | Token, proposal state, explicit consent |
| `GET /api/health` | Infrastructure | Process liveness | No sensitive data |
| `GET /api/readiness` | Infrastructure | Minimal readiness | No credential names/details |

## Operator

All operator endpoints require bearer token or authenticated session. Session state changes also require CSRF.

| Method/path | Used by | Result |
|---|---|---|
| `GET /api/operator/readiness` | Settings/doctor-equivalent client | Provider/config detail without secret values |
| `GET /api/google/connect`, callback | Settings | OAuth connection and encrypted token storage |
| `GET /api/requests`, `/<id>` | Dashboard/API users | Search/filter/paginated requests and detail; page size is 1–100 and page number is clamped to available results |
| `POST /api/proposals/<id>/send` | Dashboard/API users | Rate-limited official WhatsApp send |
| `POST /api/appointments/<id>/book` | Dashboard/API users | Idempotent Google event creation; returns structured `409` conflicts for paused automation or a slot that became busy, sanitized/retryable `502` when availability could not be checked before any write, and non-retryable `502` when Google may have accepted a create and reconciliation is required |
| `POST /api/appointments/<id>/reconcile` | Dashboard/API users | Read-only verification of the current booking-attempt Calendar event; restores booked state only for a verified matching event, or enables an explicit retry when absent; never sends WhatsApp |
| `POST /api/appointments/<id>/cancel` | Dashboard/API users | Claims a booked appointment, cancels the Google event, then atomically stops reminders and marks local state cancelled; ambiguous provider outcomes return non-retryable `502 calendar_cancellation_unverified` and require reconciliation before another cancellation attempt |
| `POST /api/appointments/<id>/reconcile-cancel` | Dashboard/API users | Read-only event verification after an ambiguous cancellation; absent event completes cancellation, present event restores booked state for a separate explicit retry |
| `GET /api/audit` | Audit view/API users | Workspace-scoped event history, clamped to 1–500 rows |
| `GET /api/contacts/<id>/export` | Privacy workflow | Downloadable contact JSON export containing contact, decrypted messages, scheduling requests, proposal drafts/slots, linked provider delivery receipts, and appointments; excludes recipient IDs and booking tokens and records successful exports in the audit trail |
| `DELETE /api/contacts/<id>` | Privacy workflow | Deletes contact/domain data only after related appointments are cancelled; returns `409 contact_has_unresolved_appointments` otherwise |
| `GET /api/export/requests.csv` | Dashboard/API users | Workspace CSV export |

The personal WhatsApp screen is session-only (not bearer API): `POST /actions/assisted/analyze` performs transient local analysis and a Calendar availability query, while `POST /actions/assisted/<id>/shared` activates the private booking link only after the operator confirms manual sharing. Both require CSRF and create no WhatsApp API calls.

Browser contact deletion is handled by `POST /actions/contacts/<id>/delete`, not the bearer API: it requires the authenticated operator session, CSRF, a fresh current-password check, and an IP-scoped attempt limit. It refuses contacts with unresolved appointments; the operator must cancel or resolve those appointments separately first.

Appointment rescheduling is currently an operator-browser workflow, not a bearer API: prepare the proposed time with `POST /actions/appointments/<id>/reschedule`, explicitly confirm with `/reschedule/confirm`, or discard with `/reschedule/discard`. All routes require session + CSRF. Preparation rechecks Calendar availability and does not write to the provider. Confirmation narrowly patches event start/end, verifies the actual returned Calendar event, and only then updates local appointment and queued reminder state. Appointment-state/time transitions also touch the parent request's cursor timestamp so HAI incremental clients are notified. Provider ambiguity enters `reschedule_manual_required`; use the read-only `/reschedule/reconcile` action, which accepts only the stored original or proposed event times. Stale `rescheduling` claims are moved to manual review by the worker without another provider write.

Stale booking reconciliation is available through the session-protected, CSRF-checked `POST /actions/appointments/<id>/reconcile` route or the bearer-authenticated API route above. Provider lookup errors are sanitized and leave the `manual_required` state unchanged. A verified event restores the appointment and request to `booked` atomically. If no event exists, the appointment becomes `failed` and the operator may separately choose **Retry booking**. First attempts preserve the original deterministic event ID; an explicit retry advances a persisted attempt counter and uses a distinct deterministic ID, so a cancelled/tombstoned ID cannot make the retry fail forever. Recovery does not send WhatsApp confirmation; follow-up remains manual.

Calendar cancellation uses the same fail-closed principle. The app first claims the local appointment as `cancelling`, then deletes the Calendar event, and only after success atomically cancels the appointment, request, and reminder jobs. A provider timeout or process interruption can leave the provider outcome unknown; the worker moves stale `cancelling` records to `cancel_manual_required` without making another provider call. Use `POST /actions/appointments/<id>/reconcile-cancel` (session + CSRF) or the API route above to perform a read-only event lookup. An absent event completes local cancellation; a still-active event restores `booked`, after which a separate explicit cancellation may be attempted. Do not repeat cancellation while its state is unresolved.

## External provider calls

- Google `freebusy.query`: real calendar availability.
- Google `events.insert/get/update/delete`: event lifecycle; a stable attempt-specific event ID makes same-attempt retries idempotent, while an explicit retry after a read-only no-event reconciliation gets a new ID.
- Meta Graph `/{phone-number-id}/messages`: text proposals/confirmations and approved reminder templates.
- WhatsApp `https://wa.me/?text=...` is only a browser link with a prefilled draft; the operator must choose a recipient and send. Agenda Relay makes no personal WhatsApp API call.

HTTP 200 from Meta means API acceptance, not confirmed delivery/read. Signed callbacks for known status values (`sent`, `delivered`, `read`, `failed`, `deleted`) are stored as idempotent provider-reported receipts, with only the provider message ID, status, event time, bounded error code, and local receipt time. Out-of-order callbacks remain in the event history; the UI selects the latest provider timestamp. Missing callbacks do not imply delivery, and receipts do not automatically resend or advance booking state. The personal assisted mode has no provider status channel.

