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

After the proposal is sent through official WhatsApp Cloud API, the contact can reply with 1, 2, or 3. The app resolves that reply only against the contact's most recent sent proposal. The contact can alternatively choose through `/book/<private-token>` and must check an explicit consent box.

Confirmation creates exactly one pending appointment for the request.

## 5. Google Calendar event

The operator chooses **Book confirmed slot**. Agenda Relay claims the appointment atomically and inserts a deterministic Google event ID. A retry after a provider 409 fetches the existing event instead of duplicating it. Only a stored, verified email is sent as a Calendar attendee; a WhatsApp display name is never treated as an email.

If event creation succeeds but WhatsApp confirmation fails, the appointment remains truthfully booked and the dashboard/audit trail flags communication attention.

## 6. Confirmation and reminders

The booking confirmation is sent after the event write. A reminder job is queued at the configured offset. The worker uses an approved WhatsApp template when configured. Without one, an out-of-window reminder becomes `manual_required`; it is never labelled sent.

## 7. Audit and recovery

All state transitions, authentication events, provider success/failure, pause changes, reminder outcomes, privacy operations, and retention purges are timestamped. Ambiguous provider timeouts are not automatically retried. The operator reviews and resolves them to avoid duplicate external actions.

## Smoke-test evidence

`tests/test_critical_path.py::test_message_to_proposal_to_confirmation_to_calendar_event` executes the full path with strict test-only provider fakes and proves booking idempotency. Real-provider proof remains blocked by credentials and account approvals.
