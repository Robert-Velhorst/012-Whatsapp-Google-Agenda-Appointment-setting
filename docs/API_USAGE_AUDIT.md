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
| `POST /api/appointments/<id>/book` | Dashboard/API users | Idempotent Google event creation |
| `POST /api/appointments/<id>/reconcile` | Dashboard/API users | Read-only verification of the current booking-attempt Calendar event; restores booked state only for a verified matching event, or enables an explicit retry when absent; never sends WhatsApp |
| `POST /api/appointments/<id>/cancel` | Dashboard/API users | Calendar cancellation and job stop |
| `GET /api/audit` | Audit view/API users | Workspace-scoped event history, clamped to 1–500 rows |
| `GET /api/contacts/<id>/export` | Privacy workflow | Downloadable contact JSON export containing contact, decrypted messages, scheduling requests, proposal drafts/slots, linked provider delivery receipts, and appointments; excludes recipient IDs and booking tokens and records successful exports in the audit trail |
| `DELETE /api/contacts/<id>` | Privacy workflow | Deletes contact/domain data only after related appointments are cancelled; returns `409 contact_has_unresolved_appointments` otherwise |
| `GET /api/export/requests.csv` | Dashboard/API users | Workspace CSV export |

The personal WhatsApp screen is session-only (not bearer API): `POST /actions/assisted/analyze` performs transient local analysis and a Calendar availability query, while `POST /actions/assisted/<id>/shared` activates the private booking link only after the operator confirms manual sharing. Both require CSRF and create no WhatsApp API calls.

Browser contact deletion is handled by `POST /actions/contacts/<id>/delete`, not the bearer API: it requires the authenticated operator session, CSRF, a fresh current-password check, and an IP-scoped attempt limit. It refuses contacts with unresolved appointments; the operator must cancel or resolve those appointments separately first.

Stale booking reconciliation is available through the session-protected, CSRF-checked `POST /actions/appointments/<id>/reconcile` route or the bearer-authenticated API route above. Provider lookup errors are sanitized and leave the `manual_required` state unchanged. A verified event restores the appointment and request to `booked` atomically. If no event exists, the appointment becomes `failed` and the operator may separately choose **Retry booking**. First attempts preserve the original deterministic event ID; an explicit retry advances a persisted attempt counter and uses a distinct deterministic ID, so a cancelled/tombstoned ID cannot make the retry fail forever. Recovery does not send WhatsApp confirmation; follow-up remains manual.

## External provider calls

- Google `freebusy.query`: real calendar availability.
- Google `events.insert/get/update/delete`: event lifecycle; a stable attempt-specific event ID makes same-attempt retries idempotent, while an explicit retry after a read-only no-event reconciliation gets a new ID.
- Meta Graph `/{phone-number-id}/messages`: text proposals/confirmations and approved reminder templates.
- WhatsApp `https://wa.me/?text=...` is only a browser link with a prefilled draft; the operator must choose a recipient and send. Agenda Relay makes no personal WhatsApp API call.

HTTP 200 from Meta means API acceptance, not confirmed delivery/read. Signed callbacks for known status values (`sent`, `delivered`, `read`, `failed`, `deleted`) are stored as idempotent provider-reported receipts, with only the provider message ID, status, event time, bounded error code, and local receipt time. Out-of-order callbacks remain in the event history; the UI selects the latest provider timestamp. Missing callbacks do not imply delivery, and receipts do not automatically resend or advance booking state. The personal assisted mode has no provider status channel.

