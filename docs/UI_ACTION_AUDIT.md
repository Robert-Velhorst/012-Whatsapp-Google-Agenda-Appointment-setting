# UI action audit

| Surface/control | Server route | Authorization | Real effect | Failure/status behavior |
|---|---|---|---|---|
| Operator login | `POST /login` | Password hash + CSRF | Creates one-hour operator session | Generic incorrect-password message; audit failure |
| Sign out | `POST /logout` | Session + CSRF | Clears session | Rejects invalid CSRF |
| Pause/resume | `POST /actions/automation/toggle` | Session + CSRF | Writes persistent emergency state | Banner/status changes; inbound remains record-only |
| Search/filter | `GET /?view=scheduling` | Session | Workspace-scoped SQL search/status/pagination | Empty result explains next action |
| Review proposal | `POST /actions/proposals/<id>/send` | Session + CSRF | Official WhatsApp Cloud API text send | Failure stored as `send_failed`; no fake sent state |
| Book confirmed slot | `POST /actions/appointments/<id>/book` | Session + CSRF | Idempotent Google Calendar event and confirmation | Event success/confirmation failure split truthfully |
| Open calendar | External event link | Session page | Opens provider-returned `htmlLink` | Shown only after real event response |
| Cancel appointment | `POST /actions/appointments/<id>/cancel` | Session + CSRF | Deletes Google event and cancels jobs | Error retained; repeated cancellation does not duplicate |
| Contact save | `POST /actions/contacts/<id>/update` | Session + CSRF | Updates name/email/timezone/language/consent | Server validation and error flash |
| Connect Google Calendar | `GET /api/google/connect` | Session or API token | Starts state-bound OAuth | Missing client file returns truthful error |
| Export CSV | `GET /api/export/requests.csv` | Session/API | Exports current workspace rows | No cross-workspace rows |
| Public slot choice | `POST /book/<token>` | Private token + consent | Creates one pending appointment | Closed token state shown; no event write yet |

Navigation links render real server views: Overview/Scheduling, Contacts, Audit, Settings/readiness, and Help. No visible button is a placeholder or no-op.

Remaining UI limitations: destructive contact deletion is API-only; team/role management and provider credential entry are deliberately not exposed in the browser because they require a stronger identity/secret-management design.
