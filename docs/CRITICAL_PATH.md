# Critical path

## State sequence

`detected -> proposal_pending -> awaiting_confirmation -> slot_confirmed -> booking_pending -> booked`

Safe exception states are `needs_clarification`, `failed`, and `cancelled`. Transitions are validated in `scheduler/domain.py` and recorded in `audit_events`.

## 1. Incoming conversation

Meta calls `POST /webhook/whatsapp`. The request must contain a valid `X-Hub-Signature-256`. The app accepts text messages only, rejects oversized requests, stores each Meta message ID once, encrypts the body, and keeps context inside the configured workspace and sender.

When automation is paused, signed inbound messages are still recorded but no provider action or proposal is generated.

## 2. Detect appointment intent

The local deterministic provider inspects up to twelve recent sender messages. It recognizes Dutch and English scheduling language, explicit/tomorrow/weekday dates, bounded durations, language, title, and confidence. Conversation text never leaves the process for AI analysis.

## 3. Propose slots

Google FreeBusy is queried for business-hour gaps in the configured timezone. Three future weekday slots are stored with a private booking token. The default state is `pending_approval`. The operator can inspect the conversation, confidence, timezone, consent, and slots before sending.

## 4. User confirms

After a proposal is accepted by the official WhatsApp Cloud API, signed status callbacks can report sent, delivered, read, failed, or deleted. The app stores these receipts idempotently and displays the latest provider timestamp; a missing callback remains unknown and never causes a retry or booking transition. The contact can reply with 1, 2, or 3. The app resolves that reply only against the contact's most recent unexpired sent proposal. The contact can alternatively choose through `/book/<private-token>` and must check an explicit consent box. The public form is CSRF-protected and displays slots in the saved contact timezone.

Confirmation atomically closes the proposal and creates exactly one pending appointment for the request, including under concurrent replies.

## 5. Google Calendar event

The operator chooses **Book confirmed slot**. Agenda Relay claims the appointment atomically and inserts a deterministic Google event ID for that booking attempt. A same-attempt retry after a provider 409 fetches the existing event instead of duplicating it. If stale-booking reconciliation verifies that no event exists, an explicit operator retry advances the persisted attempt number and gets a new deterministic ID; this avoids reusing a cancelled/tombstoned event ID. Only a stored, verified email is sent as a Calendar attendee; a WhatsApp display name is never treated as an email.

Cancellation is also a recoverable provider operation. The app first claims a booked appointment as `cancelling`, deletes the Calendar event, and only then commits local appointment/request cancellation and reminder-job cancellation together. If the provider result or local completion is interrupted, the record is not treated as safely cancelled: the worker surfaces stale claims as `cancel_manual_required`, and the operator must perform a read-only Calendar reconciliation before an explicit retry. Reconciliation completes cancellation when the event is absent or restores the appointment to `booked` when it remains active. It never repeats a provider delete itself.

If event creation succeeds but a Business API WhatsApp confirmation fails, the appointment remains truthfully booked and the dashboard/audit trail flags communication attention. In assisted personal mode, no API send is attempted; the audit records `confirmation.manual_required` and the dashboard provides a draft for the operator to send.

## 6. Confirmation and reminders

The booking confirmation is sent after the event write. A reminder job is queued at the configured offset. The worker uses an approved WhatsApp template when configured. Without one, an out-of-window reminder becomes `manual_required`; it is never labelled sent.

## 7. Audit and recovery

All state transitions, authentication events, provider success/failure, pause changes, reminder outcomes, privacy operations, and retention purges are timestamped. Ambiguous provider timeouts are not automatically retried. Stale send, booking, and worker claims are recovered to manual review after 15 minutes so a process crash cannot silently strand or replay external work. For a stale Calendar booking, an operator can run a read-only lookup of the current attempt's deterministic event ID. Only an active, confirmed event with the expected appointment marker and exact start/end times restores `booked`; absence changes the appointment to an explicitly retryable failure. Lookup errors or mismatches leave it in manual review. An explicit retry increments the persisted attempt and uses a fresh event ID. Reconciliation sends no WhatsApp confirmation, so the operator must follow up manually.

## Smoke-test evidence

`tests/test_critical_path.py::test_message_to_proposal_to_confirmation_to_calendar_event` executes the full path with strict test-only provider fakes and proves booking idempotency. Real-provider proof remains blocked by credentials and account approvals.
