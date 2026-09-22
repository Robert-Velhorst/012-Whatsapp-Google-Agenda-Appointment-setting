# Operator runbook

## Daily start

1. Run `python -m scheduler.cli doctor`.
2. Confirm the dashboard names the expected environment and workspace.
3. Verify WhatsApp and Google Calendar readiness.
4. Review **Provider attention** and `manual_required` reminders before processing new proposals.

## Review a proposal

Read the conversation excerpt, requested date, duration, timezone, confidence, and proposed slots. Confirm the contact is appropriate and no private/sensitive topic was misclassified. Choose **Review proposal** only when the displayed outbound text is accurate.

## Book a confirmed slot

Confirm the selected time and consent state. Add a verified email under Contacts only when the contact supplied it. Choose **Book confirmed slot** once. A successful result includes a Google Calendar link. If the UI says the event was booked but confirmation failed, do not book again; send/resolve the confirmation manually.

## Reminders

Run the worker continuously or on a schedule. A queued reminder without `WHATSAPP_REMINDER_TEMPLATE` becomes `manual_required`. Do not reinterpret that as delivery. Configure only a Meta-approved utility template whose parameter order matches title and local date/time.

## Emergency pause

Choose **Pause automation** when credentials may be compromised, provider responses are inconsistent, the calendar is wrong, or duplicate-action risk exists. Pause stops proposal sends, event changes, and worker execution. Signed inbound messages remain stored. Investigate the audit trail, rotate credentials if necessary, run `doctor`, then resume.

## Backup and restore

Create a consistent backup with `python -m scheduler.cli backup --output C:\secure\agenda.sqlite3`. Store it encrypted. To restore, stop web and worker processes, validate the exact file, then run `python -m scheduler.cli restore <path> --confirm RESTORE`. The command preserves the previous database beside the active file with `.pre-restore` suffix. Run `doctor` and a read-only dashboard check before restart.

## Privacy request

Export the contact first when requested. Deletion is intentionally API-only because it is destructive; authenticate with the admin bearer token and issue `DELETE /api/contacts/<id>`. Verify the contact no longer appears and retain the minimal deletion audit event.

## Incident support bundle

Run `python -m scheduler.cli support-bundle`. The ZIP includes readiness, non-sensitive runtime facts, and action names/timestamps. It excludes secrets, conversation content, phone numbers, emails, token files, and the database.

## Release/rollback

1. Pause automation and create a backup.
2. Deploy the image to one canary instance with the worker stopped.
3. Run migrations and `doctor`.
4. Verify login, dashboard, provider readiness, and one consented end-to-end appointment.
5. Start one worker and monitor audit/job outcomes.
6. Roll back the application image on regression. Restore the database only when a migration/data problem is proven; forward-only migrations make application rollback safer than data rollback.
