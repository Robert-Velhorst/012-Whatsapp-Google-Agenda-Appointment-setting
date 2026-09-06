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

For Windows 11, obtain `AgendaRelay-Windows-x64.zip` from a successful Windows package workflow on this branch, or build it using `windows/Build-Windows.ps1`. Extract the entire archive to a permanent writable folder. Python is bundled; keep the executable and its `_internal` directory together.

Open PowerShell in the extracted folder and initialize a new installation:

```powershell
.\AgendaRelay.exe --setup
```

Choose and repeat an operator password of at least 12 characters. Setup generates independent application secrets, stores a password hash, and writes `.env`. It refuses to overwrite an existing `.env`, because replacing its encryption key would make stored data unreadable. If `.env` already exists, keep its keys and finish configuration in that file.

Add the Meta and Google settings described below, then run `AgendaRelay.exe` from that same folder. Open [http://127.0.0.1:5000/login](http://127.0.0.1:5000/login) and sign in with your chosen password. The executable runs the web application and reminder worker together. Keep the computer awake and the process running to receive messages.

For source installation, Python 3.11–3.13 is supported; Python 3.13 is used by the package workflow:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m scheduler.cli setup
python -m scheduler.cli migrate
python run.py
```

The source setup command performs the same password and key initialization as the executable. `python run.py` runs only the web app: start the worker in another terminal using `python -m scheduler.cli worker`. Alternatively use the Windows start script below, which launches both processes.

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

## Who this tool is for

Agenda Relay is a scheduling desk for one operator using one configured Google Calendar and a WhatsApp Business integration. A contact can ask for an appointment in WhatsApp, receive suggested times, and choose a time in the conversation. They do not need to enter a name or email into a separate booking form. The optional private link provides another way to choose a proposed time.

The operator connects the accounts once, sets business hours and meeting duration, and reviews proposals and bookings by default. Automatic sending and booking are separate opt-in settings. The application does not read an arbitrary personal WhatsApp inbox: it processes incoming text webhooks delivered to the configured Meta integration. It does not import old chat exports, voice notes, images, or group history.

## Architecture and developer guide

The frontend is server-rendered Flask/Jinja with local CSS and JavaScript assets. There is no separate React build, Node service, message broker, hosted AI requirement, or external database server. Python coordinates the provider adapters and SQLite stores the workflow state.

| Source | Responsibility |
|---|---|
| `scheduler/app.py` | Browser pages, authentication, CSRF, webhook and operator APIs |
| `scheduler/service.py` | Message analysis, proposals, confirmation, calendar booking, reminders and recovery |
| `scheduler/intent.py` | Local English/Dutch rules and the replaceable `IntentProvider` interface |
| `scheduler/calendar.py` | Google OAuth, FreeBusy, event creation and cancellation |
| `scheduler/whatsapp.py` | Meta signatures, replies, templates and ambiguous-delivery errors |
| `scheduler/store.py` | SQLite queries, ownership filters, atomic claims and audit history |
| `scheduler/migrations.py` | Forward schema migration ledger |
| `scheduler/crypto.py` | Sensitive-field encryption |
| `scheduler/setup.py` | First-run password and security-key initialization |
| `scheduler/cli.py` | Operator commands |
| `scheduler/standalone.py` | Packaged server with embedded worker |
| `scheduler/templates/`, `scheduler/static/` | Operator and booking interface |
| `tests/` | Isolated regression and workflow tests with test-only provider adapters |
| `windows/` | Source installation, start/stop, ngrok and package scripts |

The database holds workspaces, contacts, inbound messages, scheduling requests, proposals, appointments, background jobs, audit events, rate events, system state and schema versions. Migrations run during application initialization; `python -m scheduler.cli migrate` explicitly initializes/applies them. Back up before upgrading. There are no automatic downgrade migrations.

The main request lifecycle is `detected → proposal_pending → awaiting_confirmation → slot_confirmed → booking_pending → booked`. Failure, clarification and cancellation states describe exceptions. Proposal sends and appointment writes have separate atomic claims. A deterministic Google event ID supports recovery from duplicate insertion attempts; it does not reserve a proposed time against unrelated calendar edits.

## Configuration reference

Start from [.env.example](.env.example). Set values locally; do not commit `.env`. Restart the application after editing it. Boolean options use `true` or `false`.

| Setting | Purpose / default |
|---|---|
| `APP_ENV` | `development`, `test`, or `production`; default development |
| `PUBLIC_BASE_URL` | Base URL used in booking links and OAuth callbacks; local default `http://127.0.0.1:5000` |
| `WORKSPACE_ID`, `WORKSPACE_NAME`, `OPERATOR_NAME` | Single configured workspace identity and operator display label |
| `DATABASE_PATH` | SQLite file; default `./data/scheduler.sqlite3` |
| `FLASK_SECRET_KEY` | Session-signing secret; generated by setup |
| `ADMIN_API_TOKEN` | Bearer credential for operator APIs; generated by setup |
| `ADMIN_PASSWORD_HASH` | Hashed browser-login password; generated by setup |
| `DATA_ENCRYPTION_KEY` | Encryption secret for sensitive fields and Google tokens; preserve across upgrades |
| `WHATSAPP_VERIFY_TOKEN` | Webhook verification value; generated locally and registered with Meta |
| `WHATSAPP_APP_SECRET` | Meta application secret for signature verification |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | Meta account credentials required for sending |
| `WHATSAPP_GRAPH_API_VERSION` | Adapter version setting; example uses `v23.0`; check support before deployment |
| `WHATSAPP_REMINDER_TEMPLATE` | Approved template name; reminders become manual when absent |
| `GOOGLE_CLIENT_SECRETS_FILE` | Path to OAuth web-client JSON outside the repository |
| `GOOGLE_TOKEN_FILE` | Encrypted OAuth token file; default `./data/google-token.json` |
| `GOOGLE_CALENDAR_ID` | Calendar to inspect and write; default `primary` |
| `TIMEZONE` | Business-hours timezone; default `Europe/Amsterdam` |
| `AUTO_SEND_SUGGESTIONS` | Automatically send generated proposals; default false |
| `AUTO_BOOK_CONFIRMED` | Automatically book a contact's confirmed selection; default false |
| `AUTOMATION_PAUSED` | Initial pause default; the dashboard's persisted pause state takes precedence |
| `BUSINESS_HOURS_START`, `BUSINESS_HOURS_END` | Integer local hours; defaults 9 and 17, weekdays only |
| `SLOT_INTERVAL_MINUTES` | Candidate spacing: 5, 10, 15, 20, 30 or 60; default 30 |
| `DEFAULT_DURATION_MINUTES` | Fallback meeting duration; default 30 |
| `REMINDER_MINUTES_BEFORE` | Reminder offset; default 1440 (one day) |
| `DATA_RETENTION_DAYS` | Worker purge age for inbound messages and rate-event history; default 30 |
| `BOOKING_LINK_TTL_HOURS` | Proposal lifetime after sending; default 168 (seven days) |
| `MAX_OUTBOUND_PER_CONTACT_PER_HOUR` | Atomic per-contact send-attempt allowance; default 10 |
| `HAI_CONNECTOR_ENABLED` | Enables the metadata feed; default false |
| `HAI_ALLOWED_NETWORKS` | Allowed client CIDRs; defaults to IPv4/IPv6 loopback |
| `HAI_FEED_PAGE_SIZE` | Feed page size, 1–500; default 100 |
| `HAI_PROJECT_KEY` | HAI project mapping label |
| `NGROK_DOMAIN` | Assigned hostname for the guarded public tunnel |
| `NGROK_CONFIG_FILE` | Optional ngrok authentication-config path |
| `NGROK_INSPECTOR_PORT` | Dedicated local inspector port; default 4042 |
| `PORT` | Local web port; default 5000 |
| `WORKER_INTERVAL_SECONDS` | Standalone/source-launcher polling interval; default 30 |
| `WAITRESS_THREADS`, `WAITRESS_CONNECTION_LIMIT` | Packaged server limits; defaults 4 and 100 |
| `BIND_HOST` | Python/packaged bind address; default loopback; not listed in the example file |
| `GOOGLE_CLIENT_SECRETS_FILE_HOST` | Docker Compose host path for the read-only OAuth credential mount |

The source Windows launcher fixes Waitress at four threads and 100 connections. Docker Compose fixes host port 5000 and the worker interval at 30 seconds; change the Compose definition to alter those values.

## Daily operation and troubleshooting

Sign in, inspect Settings/readiness, then review the scheduling queue. Open a contact's request to inspect the message, slots, timezone and audit events. Sending requires valid Meta credentials. Booking requires a contact-confirmed choice and valid Google authorization. A green health endpoint means the web application is running; it does not prove real message delivery or calendar access.

`GET /api/readiness` returns 503 while providers are incomplete or automation is paused. `GET /api/operator/readiness` provides details under operator authentication. `GET /api/requests/<id>`, `/api/audit` and `/api/export/requests.csv` support inspection/export. Contact privacy export/deletion use `/api/contacts/<id>/export` and `DELETE /api/contacts/<id>`. Browser mutations require a CSRF token; authenticated API clients may use the bearer credential.

Pause from the dashboard before investigating an incident. Signed incoming messages continue to be stored while paused, but are not automatically replayed on resume. The worker still performs stale-claim recovery and proposal expiry while paused; reminder sending and retention purging wait until resumed.

If delivery times out, inspect Meta before resending. Stale claims older than 15 minutes move into manual review. The software has no general manual-resolution UI for these ambiguous states. Do not change database status to force a retry without reconciling provider state.

For backups use `python -m scheduler.cli backup --output C:\safe\agenda.sqlite3`. Store the encryption key and OAuth configuration securely alongside the backup policy: a database copy alone cannot recover encrypted content. Stop all web/worker processes before restoring, use the explicit `restore ... --confirm RESTORE` command, then restart. Database restoration does not undo provider events or sent messages. Support bundles omit conversation bodies and credentials; inspect diagnostic output before sharing.

## Public access and HAI operation

ngrok forwards public HTTPS requests to the application on your Windows computer. It does not move the application or database into hosted cloud infrastructure. The computer, network connection, web process, worker and tunnel must remain available. Match `PUBLIC_BASE_URL` to `https://<NGROK_DOMAIN>` and use the dedicated `windows/Start-Ngrok.ps1` script after production configuration and local readiness pass. The script refuses development exposure and verifies the assigned URL. Resolve any existing endpoint conflict without pooling traffic with another application.

Google OAuth bootstrap and production HTTPS/session configuration need an operator-controlled deployment sequence: the launcher requires Google readiness before exposing the app, while Google connection needs the registered callback to be reachable. The current scripts do not automate that initial consent/ingress setup. See [Windows/ngrok](docs/WINDOWS_AND_NGROK.md) and [operator runbook](docs/OPERATOR_RUNBOOK.md).

For HAI, enable the feed and configure an owner-scoped `json-feed` source using `http://127.0.0.1:5000/api/integrations/hai/feed`. The envelope is `{ "items": [], "nextCursor": "..." }`; send the returned cursor with the next request. The feed contains request state, duration, timezone and timestamps, not contact names, messages, tokens or calendar URLs. Network allowlisting protects this endpoint; it has no separate bearer authentication. HAI must enforce source ownership and access control. Docker-to-host networking requires specific observed gateway allowlisting, described in [HAI integration](docs/HAI_INTEGRATION.md).

## Limits and release evidence

- Intent analysis uses local English/Dutch rules, not a general language model. It recognizes scheduling keywords, some dates, weekdays and bounded durations; it does not reliably understand arbitrary negotiation, negation, time-of-day preferences, complex recurrence or travel constraints.
- WhatsApp confirmation accepts a single explicit selection or supported affirmative phrase. Questions, multiple choices, refusals and incidental numbers are not confirmations. The public choice form is available for other phrasing.
- Availability is queried during proposal generation. Missing calendar data stops suggestions. Slots are not held, and a final conflict recheck before event insertion is not implemented; another calendar writer can occupy a proposed slot before booking.
- Only one configured calendar/workspace/operator is supported. There is no team authorization, multi-calendar intersection, billing, SSO, general import, or end-user rescheduling flow.
- Reminders always use the configured template in the current worker. There is no delivery/read-status tracking, and provider API acceptance is not proof that a contact read a message.
- Contact metadata and scheduling timestamps are not all field-encrypted. Use protected local storage and backups. Retention purging is not a complete deletion policy for every domain table; use explicit privacy operations as appropriate.
- Source declarations identify the project license as Proprietary. Repository visibility alone is not permission to redistribute it.

Historical Windows, Docker, browser and benchmark results are recorded in [final verification](docs/FINAL_VERIFICATION_REPORT.md) and [performance](docs/PERFORMANCE.md). Those measurements are dated evidence, not guarantees for a new deployment. Real Meta/Google acceptance remains a separate operator step. Run the current suite with `python -m pytest -q`; run `python -m scripts.benchmark --records 1000 --reads 500` for a local baseline. Package with `windows/Build-Windows.ps1`, then smoke-test with `windows/Test-Package.ps1`. GitHub CI verifies tests, compilation, dependencies and Docker; the Windows workflow builds and tests the executable.

For maintenance and contributions, inspect [technical audit](docs/TECHNICAL_AUDIT.md), [API audit](docs/API_USAGE_AUDIT.md), [UI audit](docs/UI_ACTION_AUDIT.md), [maintenance](docs/MAINTENANCE.md), [troubleshooting](docs/TROUBLESHOOTING.md), [worklog](docs/CODEX_WORKLOG.md), [checkpoints](docs/CODEX_CHECKPOINTS.md), [task graph](docs/TASK_GRAPH.md), and [changelog](CHANGELOG.md). Add regression coverage for scheduling behavior, keep provider fakes in tests, and update the operational documentation when interfaces or setup change.
