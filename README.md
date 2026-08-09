# Agenda Relay

Agenda Relay turns consented WhatsApp Cloud API conversations into reviewed time proposals, confirmed slots, Google Calendar events, reminders, and an auditable operator workflow.

It uses official provider APIs only. There is no WhatsApp Web scraping, browser automation, fake provider success, or automatic calendar write before a contact confirms a specific slot. The default mode requires operator approval before both sending a proposal and creating a calendar event.

## Working critical path

1. Meta delivers a signed WhatsApp text webhook.
2. Agenda Relay verifies the HMAC signature, deduplicates the message, encrypts its body at rest, and derives scheduling intent from the sender's recent context.
3. Google Calendar FreeBusy returns real availability and the app prepares three timezone-aware slots.
4. The operator reviews and sends the proposal, or explicitly enables `AUTO_SEND_SUGGESTIONS`.
5. The contact replies with `1`, `2`, or `3`, or uses the private booking link and grants scheduling consent.
6. The operator reviews the confirmed slot and creates an idempotent Google Calendar event, or explicitly enables `AUTO_BOOK_CONFIRMED`.
7. Agenda Relay sends the confirmation and queues a reminder. Outside WhatsApp's permitted conversation window, reminders require an approved template; otherwise they remain visibly `manual_required`.
8. Every state change and external action is recorded in the audit trail.

## Local installation (Windows PowerShell)

For the least technical Windows 11 setup, download `AgendaRelay-Windows-x64.zip`, extract it, copy `.env.example` to `.env`, configure the providers, and run `AgendaRelay.exe`. Python is bundled. The source-based guided setup is:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
Copy-Item .env.example .env
python -m scheduler.cli hash-password
python -m scheduler.cli migrate
python run.py
```

Put the generated password hash in `ADMIN_PASSWORD_HASH`. Generate long random values for `FLASK_SECRET_KEY`, `ADMIN_API_TOKEN`, and `DATA_ENCRYPTION_KEY`. Open [http://127.0.0.1:5000/login](http://127.0.0.1:5000/login).

The included Windows launchers install, start, stop, package, and smoke-test the application. See [Windows 11 and ngrok](docs/WINDOWS_AND_NGROK.md).

Development mode is visibly labelled and may start with incomplete provider settings. `APP_ENV=production` fails closed unless HTTPS, strong secrets, encryption, WhatsApp credentials, and Google client credentials are configured.

## Provider onboarding

### Google Calendar

1. Enable Google Calendar API in a Google Cloud project.
2. Create an OAuth Web application client.
3. Register `${PUBLIC_BASE_URL}/api/google/callback` as an exact redirect URI.
4. Store the client JSON outside the repository and set `GOOGLE_CLIENT_SECRETS_FILE`.
5. Sign into the operator dashboard and choose **Connect Google Calendar** under Settings.

The OAuth token is encrypted with `DATA_ENCRYPTION_KEY`. The app requests only FreeBusy and Calendar Events scopes.

### WhatsApp Cloud API

1. Create or use an approved Meta WhatsApp Business app and phone-number ID.
2. Set the HTTPS callback to `${PUBLIC_BASE_URL}/webhook/whatsapp`.
3. Use `WHATSAPP_VERIFY_TOKEN` for the verification handshake and subscribe to the `messages` field.
4. Set `WHATSAPP_APP_SECRET`, `WHATSAPP_ACCESS_TOKEN`, and `WHATSAPP_PHONE_NUMBER_ID`.
5. If reminders may occur outside the customer-service window, obtain an approved utility template and set `WHATSAPP_REMINDER_TEMPLATE`.

## Commands

```powershell
python -m scheduler.cli doctor
python -m scheduler.cli migrate
python -m scheduler.cli worker --once
python -m scheduler.cli worker --interval 30
python -m scheduler.cli backup
python -m scheduler.cli support-bundle
python -m pytest -q --basetemp=.pytest-run
```

Restore is deliberately explicit and first preserves the previous database:

```powershell
python -m scheduler.cli restore C:\safe\agenda-relay-backup.sqlite3 --confirm RESTORE
```

## Docker

Create `.env`, point `GOOGLE_CLIENT_SECRETS_FILE_HOST` at the host credential JSON, then run:

```powershell
docker compose config
docker compose build
docker compose up -d
```

The Compose stack runs separate web and reminder-worker processes, mounts persistent data, uses read-only containers, and binds the app to localhost. Put an HTTPS reverse proxy in front of it before registering a Meta webhook.

## HAI connector

The optional HAI integration is a local-network-only, read-only JSON feed containing scheduling state without contact details, conversation text, booking tokens, or provider links. It is disabled by default. See [HAI integration](docs/HAI_INTEGRATION.md).

## Performance

The persistent SQLite/WAL path is measured at 601.5 request records per second with 4.792 ms median dashboard reads over 1,000 records on the development host. Results and the repeatable benchmark are documented in [performance and resource profile](docs/PERFORMANCE.md).

## Administrative API

Operator APIs accept `Authorization: Bearer <ADMIN_API_TOKEN>`. Browser sessions use a secure session cookie and CSRF token. Key endpoints:

- `GET /api/health` and `GET /api/readiness`
- `GET /api/operator/readiness`
- `GET /api/requests` and `GET /api/requests/<id>`
- `POST /api/proposals/<id>/send`
- `POST /api/appointments/<id>/book` and `/cancel`
- `GET /api/audit`
- `GET /api/contacts/<id>/export` or `DELETE /api/contacts/<id>`

## Documentation

Start with [critical path](docs/CRITICAL_PATH.md), [security](docs/SECURITY.md), [operator runbook](docs/OPERATOR_RUNBOOK.md), [Windows/ngrok](docs/WINDOWS_AND_NGROK.md), [acceptance tests](docs/ACCEPTANCE_TESTS.md), and the honest [goal completion matrix](docs/GOAL_COMPLETION_MATRIX.md).

## Current external gates

Real-provider verification cannot be completed without the operator's Meta business/phone approval, WhatsApp access token, public HTTPS callback, Google OAuth client, consented Google account, and approved reminder template where required. Local tests use provider fakes that are confined to `tests/`; they are never selected by production configuration.
