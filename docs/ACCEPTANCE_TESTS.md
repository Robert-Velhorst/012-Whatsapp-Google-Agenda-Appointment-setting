# Acceptance tests

## Automated matrix

| Area | Evidence | Expected |
|---|---|---|
| Signed webhook | `test_health_webhook_verification_and_security_headers`, `test_bad_signature_is_rejected` | Valid verification works; unsigned POST is rejected |
| Deduplication | `test_webhook_is_idempotent_and_creates_reviewable_proposal` | One Meta message creates one request/proposal |
| Pause safety | `test_pause_records_message_but_stops_processing` | Inbound retained; no proposal/provider action |
| Intent | `tests/test_intent.py` | Dutch/English dates, bounded duration, and confirmation index |
| Critical path | `test_message_to_proposal_to_confirmation_to_calendar_event` | Proposal -> contact choice -> one calendar event -> confirmation |
| Booking link | `test_public_booking_link_requires_consent`, `test_public_booking_link_expires` | No confirmation without consent; lifetime starts when sent and then expires |
| Event idempotency | critical-path test repeat booking | Second call returns booked without second event |
| Cancellation | `test_cancel_is_idempotent_and_calls_calendar` | Provider event cancelled and local jobs stopped |
| Production guard | `test_production_configuration_fails_closed` | Unsafe production startup raises |
| Auth/CSRF | `test_api_requires_authentication`, `test_browser_login_and_csrf` | Protected data inaccessible; session mutations require CSRF |
| Redirect/CSV safety | `test_browser_login_rejects_external_next_redirect`, `test_csv_export_neutralizes_spreadsheet_formulas` | External redirects refused; spreadsheet formulas neutralized |
| Privacy/isolation | `test_contact_export_delete_and_workspace_isolation` | Export/deletion work; other workspace sees zero records |
| Encryption | `test_sensitive_message_is_encrypted_in_database` | Plain conversation absent from SQLite field |
| Jobs | `tests/test_worker.py` | Missing/unknown reminders are never reported sent |
| Concurrency/recovery | `tests/test_provider_safety.py` | Atomic rate/send/confirmation claims; ambiguous delivery and stale work require manual review |
| Calendar/token safety | `tests/test_calendar_safety.py` | Missing event cancellation is idempotent; OAuth token replacement is atomic and encrypted |
| HAI | `tests/test_hai_integration.py` | Disabled by default; local/cursor-bounded/PII-minimized; external and invalid cursor rejected |

## Runtime/package evidence

- Windows source installer, web/worker launcher, health check, and exact-process stop passed.
- Packaged `AgendaRelay.exe` returned health 200 and branded login 200, then shut down cleanly; idle working set was about 65 MiB.
- Docker image built with a 45.28 KiB final context (after excluding 181 MiB of package artifacts), ran as uid/gid 10001 `agenda`, returned health 200, and refused unsafe production startup with exit code 1.
- PowerShell launchers parse successfully; ngrok refuses development/non-ready exposure and uses an isolated inspector port. A live temporary endpoint was externally blocked by the account's already-online endpoint rather than pooled with an unrelated service.
- `pip-audit` reported no known vulnerabilities; `pip check` reported no broken requirements.
- The 1,000-record benchmark verified 601.5 writes/second and 12.036 ms dashboard p95 on the development host.

## Required real-provider acceptance

These steps must be completed by an authorized operator and cannot be simulated as production proof:

1. Deploy behind public HTTPS and run `doctor`; expected: ready, no production errors.
2. Complete Google OAuth with the intended calendar; expected: provider strip says Connected.
3. Register the Meta callback and send a consented scheduling message; expected: exactly one request appears.
4. Approve the proposal; expected: the real contact receives the exact displayed text and private link.
5. Reply with option 2; expected: request becomes Ready to book without a calendar event yet.
6. Book; expected: one event exists at option 2, optional verified attendee is invited, confirmation is accepted by Meta, audit contains provider IDs.
7. Run the due reminder with an approved template; expected: job becomes sent and Meta returns a message ID.
8. Repeat webhook and booking calls; expected: no duplicate request/event.
9. Pause automation and repeat inbound; expected: message recorded, no outbound/calendar action.
10. Export and delete the test contact; expected: personal records removed and minimal deletion audit remains.

Actual result in this workspace: 37 automated tests and the local runtime/package matrix passed; the real-provider matrix remains blocked by credentials, approvals, an available assigned ngrok endpoint, and authorized account actions.
