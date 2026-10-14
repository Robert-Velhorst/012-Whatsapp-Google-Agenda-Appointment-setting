# UI action audit

| Surface/control | Server route | Authorization | Real effect | Failure/status behavior |
|---|---|---|---|---|
| Operator login | `POST /login` | Password hash + CSRF | Creates one-hour operator session | Generic incorrect-password message; audit failure |
| Sign out | `POST /logout` | Session + CSRF | Clears session | Rejects invalid CSRF |
| Pause/resume | `POST /actions/automation/toggle` | Session + CSRF | Writes persistent emergency state | Banner/status changes; inbound remains record-only |
| Search/filter | `GET /?view=scheduling` | Session | Workspace-scoped SQL search/status/pagination | Empty result explains next action |
| Review proposal | `POST /actions/proposals/<id>/send` | Session + CSRF | Official WhatsApp Cloud API text send | Definite non-delivery is `send_failed`; ambiguous delivery is `manual_required`, never blindly retried |
| Reconcile ambiguous delivery | `POST /actions/proposals/<id>/reconcile` | Session + CSRF; workspace-scoped proposal; outcome allowlisted | Atomically records operator-verified delivery/non-delivery and audit event; never calls WhatsApp | Delivered moves proposal to awaiting contact confirmation; verified non-delivery only enables a separate explicit retry; stale or personal proposals are rejected |
| Analyze pasted personal message | `POST /actions/assisted/analyze` | Session + CSRF | Transient local intent analysis and Calendar FreeBusy query; persists structured proposal only | Ambiguous/non-scheduling text and disconnected Calendar produce a truthful error |
| Open WhatsApp with draft | `https://wa.me/?text=...` | Authenticated operator page | Opens WhatsApp with prefilled text; operator still chooses recipient and sends | Not a delivery signal; no send API is called |
| WhatsApp delivery status | Signed `POST /webhook/whatsapp` receipt, shown in the request detail | Meta HMAC + configured phone-number ID | Displays the latest provider-reported status for a Business API message | Missing/delayed receipts remain unknown; duplicate/out-of-order callbacks do not trigger resend or booking transitions; not available for personal mode |
| I sent this manually | `POST /actions/assisted/<id>/shared` | Session + CSRF | Activates the private booking link after operator confirmation | Records manual confirmation; provider delivery remains unverified |
| Book confirmed slot | `POST /actions/appointments/<id>/book` | Session + CSRF | Idempotent Google Calendar event and confirmation | Event success/confirmation failure split truthfully |
| Reconcile stale Calendar booking | `POST /actions/appointments/<id>/reconcile` | Session + CSRF; appointment must be `manual_required` | Read-only lookup of the current attempt's deterministic Google event; a matching confirmed event restores booked state atomically, otherwise makes booking explicitly retryable with a fresh ID on retry | Lookup/provider errors leave the appointment in `manual_required`; recovery never sends WhatsApp confirmation |
| Retry missing Calendar booking | `POST /actions/appointments/<id>/book` | Session + CSRF; operator explicitly initiates | Starts a new idempotent booking attempt after reconciliation found no matching event | Existing safety checks still apply; ambiguous outcomes return to manual reconciliation |
| Open calendar | External event link | Session page | Opens provider-returned `htmlLink` | Shown only after real event response |
| Cancel appointment | `POST /actions/appointments/<id>/cancel` | Session + CSRF | Claims the booked appointment, deletes the Google event, then atomically cancels local appointment/request/reminder state | A provider error or interrupted local finalization becomes `cancel_manual_required`/`cancelling`; never blindly repeats the provider delete |
| Reconcile Calendar cancellation | `POST /actions/appointments/<id>/reconcile-cancel` | Session + CSRF; appointment must be `cancel_manual_required` | Read-only event lookup; confirms cancellation if the event is absent, otherwise restores `booked` and enables a separate explicit cancel retry | Lookup/provider errors preserve the review state; no provider mutation is performed |
| Contact save | `POST /actions/contacts/<id>/update` | Session + CSRF | Updates name/email/timezone/language/consent | Server validation and error flash |
| Contact data export | `GET /api/contacts/<id>/export` | Session/API | Downloads contact, messages, scheduling requests, proposal drafts/slots, and appointment records as JSON; booking credentials are excluded | Workspace-scoped 404 for unknown contact; successful export is audited |
| Contact delete | `POST /actions/contacts/<id>/delete` | Session + CSRF + current password; five attempts per IP per 15 minutes | Deletes contact records only after all linked appointments are cancelled; never cancels a provider event as a side effect | Refused while appointments are unresolved; invalid password is audited without storing the supplied value |
| Connect Google Calendar | `GET /api/google/connect` | Session or API token | Starts state-bound OAuth | Missing client file returns truthful error |
| Export CSV | `GET /api/export/requests.csv` | Session/API | Exports current workspace rows | No cross-workspace rows |
| Public slot choice | `POST /book/<token>` | Private token + consent | Creates one pending appointment | Closed token state shown; no event write yet |

Navigation links render real server views: Overview/Scheduling, Personal WhatsApp, Contacts, Audit, Settings/readiness, and Help. No visible button is a placeholder or no-op.

Remaining UI limitations: ambiguous reminder jobs and other provider states do not yet have a general reconciliation screen; team/role management and provider credential entry are deliberately not exposed in the browser because they require a stronger identity/secret-management design.

