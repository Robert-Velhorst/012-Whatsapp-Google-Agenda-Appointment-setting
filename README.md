# Agenda Relay

Agenda Relay turns scheduling requests into reviewed time proposals, confirmed slots, Google Calendar events, reminders, and an auditable operator workflow. It supports consented WhatsApp Cloud API messages and an assisted workflow for personal WhatsApp.

The Business integration uses official provider APIs only. Personal mode opens WhatsApp with a prefilled draft for you to review and send. There is no WhatsApp Web scraping, inbox access, fake provider success, or automatic calendar write before a contact confirms a specific slot. The default mode requires operator approval before both Business API proposal sending and calendar event creation.

## Working critical path

For WhatsApp Business Cloud API:

1. Meta delivers a signed WhatsApp text webhook.
2. Agenda Relay verifies the HMAC signature, deduplicates the message, encrypts its body at rest, and derives scheduling intent from the sender's recent context.
3. Google Calendar FreeBusy returns real availability and the app prepares three timezone-aware slots.
4. The operator reviews and sends the proposal, or explicitly enables `AUTO_SEND_SUGGESTIONS`.
5. The contact replies with `1`, `2`, or `3`, or uses the private booking link and grants scheduling consent.
6. The operator reviews the confirmed slot and creates an idempotent Google Calendar event, or explicitly enables `AUTO_BOOK_CONFIRMED`.
7. Agenda Relay sends the confirmation and queues a reminder. Outside WhatsApp's permitted conversation window, reminders require an approved template; otherwise they remain visibly `manual_required`.
8. Every state change and external action is recorded in the audit trail.

For personal WhatsApp, open **Personal WhatsApp**, paste only the relevant message, review the locally detected request and suggested times, then open WhatsApp with a prepared draft. You choose the recipient and send it yourself. After confirming that you shared it, activate its private booking link. The recipient selects a time and consents on that link; Google Calendar booking then follows the configured approval or auto-book setting. Personal-account confirmations and reminders remain manual. The app does not read your personal inbox or send personal WhatsApp messages.

## Local installation (Windows PowerShell)

For Windows 11, obtain `AgendaRelay-Windows-x64.zip` from a successful Windows package workflow on this branch, or build it using `windows/Build-Windows.ps1`. Extract the entire archive to a permanent writable folder. Python is bundled; keep the executable and its `_internal` directory together.

Open PowerShell in the extracted folder and initialize a new installation:

```powershell
.\AgendaRelay.exe --setup
```

Choose and repeat an operator password of at least 12 characters. Setup generates independent application secrets, stores a password hash, and writes `.env`. It refuses to overwrite an existing `.env`, because replacing its encryption key would make stored data unreadable. If `.env` already exists, keep its keys and finish configuration in that file.

For the assisted personal flow, configure Google Calendar and a reachable HTTPS `PUBLIC_BASE_URL` for booking links; Meta settings are not required. Configure Meta as well only if you want the separate WhatsApp Business webhook/API path. Then run `AgendaRelay.exe` from that same folder. Open [http://127.0.0.1:5000/login](http://127.0.0.1:5000/login) and sign in with your chosen password. The executable runs the web application and reminder worker together. Keep the computer awake and the process running while using the app.

For source installation, Python 3.11–3.15 is supported; Python 3.15 is used by CI and packaging:

```powershell
py -3.15 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m scheduler.cli setup
python -m scheduler.cli migrate
python run.py
```

The source setup command performs the same password and key initialization as the executable. `python run.py` runs only the web app: start the worker in another terminal using `python -m scheduler.cli worker`. Alternatively use the Windows start script below, which launches both processes.

The included Windows launchers install, start, stop, package, and smoke-test the application. See [Windows 11 standalone setup](docs/WINDOWS.md). For cloud hosting, follow the [Hetzner deployment guide](docs/HETZNER_DEPLOYMENT.md).

Development mode is visibly labelled and may start with incomplete provider settings. `APP_ENV=production` fails closed unless HTTPS, strong secrets, encryption, and Google client credentials are configured. Meta credentials are required only when `WHATSAPP_CLOUD_API_ENABLED=true`; the assisted personal workflow does not require them.

## Provider onboarding

### Google Calendar

1. Enable Google Calendar API in a Google Cloud project.
2. Create an OAuth Web application client.
3. Register `${PUBLIC_BASE_URL}/api/google/callback` as an exact redirect URI.
4. Store the client JSON outside the repository and set `GOOGLE_CLIENT_SECRETS_FILE`.
5. Sign into the operator dashboard and choose **Connect Google Calendar** under Settings.

The OAuth token is encrypted with `DATA_ENCRYPTION_KEY`. The app requests only FreeBusy and Calendar Events scopes.

### WhatsApp Cloud API (optional)

1. Create or use an approved Meta WhatsApp Business app and phone-number ID.
2. Set the HTTPS callback to `${PUBLIC_BASE_URL}/webhook/whatsapp`.
3. Use `WHATSAPP_VERIFY_TOKEN` for the verification handshake and subscribe to the `messages` field.
4. Set `WHATSAPP_APP_SECRET`, `WHATSAPP_ACCESS_TOKEN`, and `WHATSAPP_PHONE_NUMBER_ID`.
5. If reminders may occur outside the customer-service window, obtain an approved utility template and set `WHATSAPP_REMINDER_TEMPLATE`.

Set `WHATSAPP_CLOUD_API_ENABLED=true` to enable the signed webhook and Business API path. Leave it `false` for personal WhatsApp assisted mode. With the Business API disabled, webhook endpoints reject requests and the app cannot send Business API messages. Existing installations that do not yet define the flag infer the setting from their existing Meta credentials; set it explicitly when changing modes.

## Commands

```powershell
python -m scheduler.cli doctor
python -m scheduler.cli migrate
python -m scheduler.cli worker --once
python -m scheduler.cli worker --interval 30
python -m scheduler.cli backup
python -m scheduler.cli rotate-encryption-key --output-dir C:\secure\agenda-relay-rotated
python -m scheduler.cli support-bundle
python -m pytest -q --basetemp=.pytest-run
```

Restore is deliberately explicit and first preserves the previous database:

```powershell
python -m scheduler.cli restore C:\safe\agenda-relay-backup.sqlite3 --confirm RESTORE
```

Encryption-key rotation is an offline operation. Stop every web/worker process, set `DATA_ENCRYPTION_KEY` to the current key and `NEW_DATA_ENCRYPTION_KEY` to a newly generated random secret of at least 64 characters, then choose a new, non-existing output directory. The command creates a verified replacement database and (when present) OAuth token file there without modifying the originals. Test the staged files with the new key before changing `DATABASE_PATH`, `GOOGLE_TOKEN_FILE`, and `DATA_ENCRYPTION_KEY` in `.env`; keep the original files as rollback copies until the rotated installation has been verified. Do not put either key on a command line or in shell history.

For a packaged Windows installation, use `AgendaRelay.exe doctor`, `AgendaRelay.exe backup`, and `AgendaRelay.exe rotate-encryption-key --output-dir <new-empty-directory>` from the package folder instead of `python -m scheduler.cli ...`; the packaged executable dispatches the same operator commands without requiring a separate Python installation.

## Docker

Create `.env`, point `GOOGLE_CLIENT_SECRETS_FILE_HOST` at the host credential JSON, then run:

```powershell
docker compose config --quiet
docker compose build
docker compose up -d
```

The Compose stack forces production-mode validation for both web and reminder-worker processes, mounts persistent data, uses read-only containers, and binds the app to localhost. It will refuse to start until `.env` contains production-strength secrets, encryption key, and provider configuration. Put an HTTPS reverse proxy in front of it before registering a Meta webhook.

## HAI connector

The optional HAI integration is a local-network-only, read-only JSON feed containing scheduling state without contact details, conversation text, booking tokens, or provider links. It is disabled by default. See [HAI integration](docs/HAI_INTEGRATION.md).

## Performance

Two serial three-run samples on this Windows 11 host (six runs total) measured 230.6–782.2 records/second, 0.660–1.344 ms median dashboard reads, 1.154–2.039 ms dashboard p95, and 4.339–10.514 ms for a 500-item HAI page. The wide spread is not a capacity guarantee and does not yet justify a write-path optimization. These local runs use a temporary database; the benchmark separates timing from Python allocation tracing. See [performance and resource profile](docs/PERFORMANCE.md).

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

Start with [critical path](docs/CRITICAL_PATH.md), [security](docs/SECURITY.md), [operator runbook](docs/OPERATOR_RUNBOOK.md), [Windows setup](docs/WINDOWS.md), [Hetzner deployment](docs/HETZNER_DEPLOYMENT.md), [acceptance tests](docs/ACCEPTANCE_TESTS.md), and the honest [goal completion matrix](docs/GOAL_COMPLETION_MATRIX.md).

## Current external gates

For the optional Business API path, real-provider verification requires Meta business/phone approval, WhatsApp credentials, public HTTPS webhook reachability, Google OAuth, a consented Google account, and an approved reminder template where required. Personal assisted mode does not require Meta; it still requires real Google Calendar OAuth and a publicly reachable HTTPS booking URL from the Hetzner deployment. Local tests use provider fakes confined to `tests/`; they are never selected by production configuration.

## Who this tool is for

Agenda Relay is a scheduling desk for one operator using one configured Google Calendar. It can process verified incoming WhatsApp Business webhooks, or assist an operator using personal WhatsApp by analyzing a message they paste, checking availability, and preparing a response with a booking link. A contact can choose a proposed time on that private link without entering a name or email.

The operator sets business hours and meeting duration and can review proposals and bookings by default. Automatic Business API sending and calendar booking are separate opt-in settings. The personal workflow is assisted, not inbox automation: the operator supplies the relevant text, the app processes it locally using deterministic English/Dutch rules, and the operator manually sends the prepared draft. Pasted text is not retained or sent to an AI or WhatsApp API; the structured request and proposal are stored in the local workflow database so the booking link can work. Do not paste unrelated or sensitive conversation content. Personal messages, confirmations, and reminders are never sent by the Business API. The app does not import chat exports, voice notes, images, or group history. WhatsApp's newer opt-in Agent Platform is separate; WhatsApp says an agent cannot access the user's other chats, and this repository does not implement that API ([WhatsApp Help Center](https://faq.whatsapp.com/1050934623978152)).

## Architecture and developer guide

The frontend is server-rendered Flask/Jinja with local CSS and JavaScript assets. There is no separate React build, Node service, message broker, hosted AI requirement, or external database server. Python coordinates the provider adapters and SQLite stores the workflow state.

| Source | Responsibility |
|---|---|
| `scheduler/app.py` | Browser pages, authentication, CSRF, webhook and operator APIs |
| `scheduler/service.py` | Message analysis, assisted personal proposals, confirmation, calendar booking, reminders and recovery |
| `scheduler/intent.py` | Local English/Dutch rules and the replaceable `IntentProvider` interface |
| `scheduler/calendar.py` | Google OAuth, FreeBusy, event creation and cancellation |
| `scheduler/whatsapp.py` | Meta signatures, replies, templates and ambiguous-delivery errors |
| `scheduler/store.py` | SQLite queries, ownership filters, atomic claims and audit history |
| `scheduler/migrations.py` | Forward schema migration ledger |
| `scheduler/crypto.py` | Sensitive-field encryption |
| `scheduler/setup.py` | First-run password and security-key initialization |
| `scheduler/cli.py` | Operator commands |
| `scheduler/standalone.py` | Packaged server with embedded worker |
| `scheduler/templates/`, `scheduler/static/` | Operator, assisted personal WhatsApp, and public booking interfaces |
| `tests/` | Isolated regression and workflow tests with test-only provider adapters |
| `windows/` | Windows source installation, start/stop, package and smoke-test scripts |

The database holds workspaces, contacts, inbound messages, scheduling requests, proposals, appointments, background jobs, audit events, rate events, system state and schema versions. Migrations run during application initialization; `python -m scheduler.cli migrate` explicitly initializes/applies them. Back up before upgrading. There are no automatic downgrade migrations.

The main request lifecycle is `detected → proposal_pending → awaiting_confirmation → slot_confirmed → booking_pending → booked`. Failure, clarification and cancellation states describe exceptions. Proposal sends and appointment writes have separate atomic claims. A persisted booking-attempt counter gives each deliberate retry a deterministic Google event ID while preserving the first-attempt ID for crash recovery. A same-attempt duplicate insert can safely recover the existing event; a new attempt is used only after an operator-triggered, read-only reconciliation finds no matching event. Event IDs do not reserve a proposed time against unrelated calendar edits.

## Configuration reference

Start from [.env.example](.env.example). Set values locally; do not commit `.env`. Restart the application after editing it. Boolean options use `true` or `false`.

| Setting | Purpose / default |
|---|---|
| `APP_ENV` | `development`, `test`, or `production`; default development |
| `PUBLIC_BASE_URL` | Base URL used in booking links and OAuth callbacks; local default `http://127.0.0.1:5000` |
| `WORKSPACE_ID`, `WORKSPACE_NAME`, `OPERATOR_NAME` | Single configured workspace identity and operator display label |
| `DATABASE_PATH` | SQLite file; default `./data/scheduler.sqlite3`, relative paths resolve from the application/package folder |
| `FLASK_SECRET_KEY` | Session-signing secret; generated by setup |
| `ADMIN_API_TOKEN` | Bearer credential for operator APIs; generated by setup |
| `ADMIN_PASSWORD_HASH` | Hashed browser-login password; generated by setup |
| `DATA_ENCRYPTION_KEY` | Encryption secret for sensitive fields and Google tokens; preserve across upgrades |
| `WHATSAPP_VERIFY_TOKEN` | Webhook verification value; generated locally and registered with Meta |
| `WHATSAPP_APP_SECRET` | Meta application secret for signature verification |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | Meta account credentials required for sending |
| `WHATSAPP_GRAPH_API_VERSION` | Adapter version setting; example uses `v23.0`; check support before deployment |
| `WHATSAPP_REMINDER_TEMPLATE` | Approved template name; reminders become manual when absent |
| `GOOGLE_CLIENT_SECRETS_FILE` | Path to OAuth web-client JSON outside the repository; relative paths resolve from the application/package folder |
| `GOOGLE_TOKEN_FILE` | Encrypted OAuth token file; default `./data/google-token.json`, relative paths resolve from the application/package folder |
| `GOOGLE_CALENDAR_ID` | Calendar to inspect and write; default `primary` |
| `TIMEZONE` | Business-hours timezone; default `Europe/Amsterdam` |
| `AUTO_SEND_SUGGESTIONS` | Automatically send generated proposals; default false |
| `AUTO_BOOK_CONFIRMED` | Automatically book a contact's confirmed selection; default false |
| `AUTOMATION_PAUSED` | Initial pause default; the dashboard's persisted pause state takes precedence |
| `BUSINESS_HOURS_START`, `BUSINESS_HOURS_END` | Integer local hours; defaults 9 and 17, weekdays only |
| `SLOT_INTERVAL_MINUTES` | Candidate spacing: 5, 10, 15, 20, 30 or 60; default 30 |
| `DEFAULT_DURATION_MINUTES` | Fallback meeting duration; default 30 |
| `REMINDER_MINUTES_BEFORE` | Reminder offset; default 1440 (one day) |
| `DATA_RETENTION_DAYS` | Worker purge age for inbound messages, rate-event history, and delivery receipts; default 30 |
| `SCHEDULING_RETENTION_DAYS` | Worker purge age for terminal scheduling records, expired proposals, completed bookings, and old cancellations; default 90 days |
| `BOOKING_LINK_TTL_HOURS` | Proposal lifetime after sending; default 168 (seven days) |
| `MAX_OUTBOUND_PER_CONTACT_PER_HOUR` | Atomic per-contact send-attempt allowance; default 10 |
| `MAX_INBOUND_PER_CONTACT_PER_HOUR` | Atomic inbound-message allowance per sender; default 10 |
| `MAX_INBOUND_TOTAL_PER_HOUR` | Atomic inbound-message allowance across the workspace; default 60 |
| `MAX_INBOUND_MESSAGES_PER_WEBHOOK` | Maximum text messages processed across one callback; 1–200, default 20 |
| `MAX_INBOUND_MESSAGE_CHARS` | Maximum stored/analyzed text length; 1–20,000, default 5,000 |
| `TRUSTED_PROXY_NETWORKS` | CIDRs allowed to supply `X-Forwarded-For` for login and contact-deletion rate limits; defaults to loopback for a same-host reverse proxy. Set only addresses of proxies that cannot be bypassed; HAI access always uses the direct peer address. |
| `HAI_CONNECTOR_ENABLED` | Enables the metadata feed; default false |
| `HAI_ALLOWED_NETWORKS` | Allowed client CIDRs; defaults to IPv4/IPv6 loopback |
| `HAI_FEED_PAGE_SIZE` | Recent HAI snapshot size, 1–500; default 100 |

Inbound quotas apply only to the optional WhatsApp Business Cloud API webhook. Duplicate provider message IDs do not consume quota. Messages over the callback or text-size limits are acknowledged but ignored. `DATA_RETENTION_DAYS` controls inbound-message, rate-event, and provider-delivery receipt cleanup. Separately, `SCHEDULING_RETENTION_DAYS` defaults to 90 days and removes old cancelled/failed requests, expired booking proposals after their expiry plus the retention period, cancelled appointments, and booked appointments only after their scheduled end is older than the retention period. Linked request/proposal rows and appointment reminder jobs are removed together. Upcoming appointments and booking failures that still need operator recovery are retained. Google Calendar events and the general audit history are not deleted. Contact and conversation data follow their separate retention and contact-deletion controls.
| `HAI_PROJECT_KEY` | HAI project mapping label |
| `PORT` | Local web port; default 5000 |
| `WORKER_INTERVAL_SECONDS` | Standalone/source-launcher polling interval; default 30 |
| `WAITRESS_THREADS`, `WAITRESS_CONNECTION_LIMIT` | Packaged server limits; defaults 4 and 100 |
| `BIND_HOST` | Python/packaged bind address; default loopback; not listed in the example file |
| `GOOGLE_CLIENT_SECRETS_FILE_HOST` | Docker Compose host path for the read-only OAuth credential mount |

The source Windows launcher fixes Waitress at four threads and 100 connections. Docker Compose fixes host port 5000 and the worker interval at 30 seconds; change the Compose definition to alter those values.

## Daily operation and troubleshooting

Sign in, inspect Settings/readiness, then review the scheduling queue. Open a contact's request to inspect the message, slots, timezone and audit events. Sending requires valid Meta credentials. Booking requires a contact-confirmed choice and valid Google authorization. A green health endpoint means the web application is running; it does not prove real message delivery or calendar access.

`GET /api/readiness` returns 503 while providers are incomplete or automation is paused. `GET /api/operator/readiness` provides details under operator authentication. `GET /api/requests/<id>`, `/api/audit` and `/api/export/requests.csv` support inspection/export. Contact privacy export/deletion use `/api/contacts/<id>/export` and `DELETE /api/contacts/<id>`. Browser mutations require a CSRF token; authenticated API clients may use the bearer credential.

Pause from the dashboard before investigating an incident. Signed incoming messages continue to be stored while paused, but are not automatically replayed on resume. The worker still performs stale-claim recovery, proposal expiry, and configured data-retention purging while paused; only outbound reminder sending waits until automation resumes.

If delivery times out, inspect Meta before resending. Stale claims older than 15 minutes move into manual review. The scheduling desk has a delivery-reconciliation action for ambiguous Business API proposals: after checking provider state, the operator can record verified delivery or non-delivery. The action never contacts WhatsApp; a verified non-delivery only enables a separate explicit retry. Other ambiguous jobs still require manual reconciliation outside the UI. Do not change database status directly to force a retry.

For backups use `python -m scheduler.cli backup --output C:\safe\agenda.sqlite3`. Backups are made with SQLite's online backup API, validated, and atomically published; the output must not be the live database file. Store the encryption key and OAuth configuration securely alongside the backup policy: a database copy alone cannot recover encrypted content. Stop all web/worker processes before restoring, use the explicit `restore ... --confirm RESTORE` command, then restart. Restore validates both SQLite integrity and the app migration schema, stages the replacement, and preserves the prior database as a timestamped `.pre-restore-*` safety copy (an unreadable database is preserved byte-for-byte). The CLI can restore without first booting the application, which allows recovery when the live database is corrupt. It fails closed while either SQLite WAL/SHM sidecar remains, including a zero-byte WAL held open by an idle connection. Database restoration does not undo provider events or sent messages. Support bundles omit conversation bodies and credentials; inspect diagnostic output before sharing.

## Public access and HAI operation

Production runs on Hetzner behind a host-managed HTTPS reverse proxy; the application container binds only to loopback. Set `PUBLIC_BASE_URL` to the final HTTPS hostname and register `${PUBLIC_BASE_URL}/api/google/callback` in Google OAuth. Configure DNS, firewall, TLS, secrets, backups and monitoring before cutover; follow [Hetzner deployment](docs/HETZNER_DEPLOYMENT.md). Keep automation paused during Google OAuth bootstrap, run the real-provider acceptance checks, and resume only after operator review. The Windows package is a standalone/local deployment and does not expose itself publicly.

For HAI, enable the feed and configure an owner-scoped `json-feed` source using `http://127.0.0.1:5000/api/integrations/hai/feed` for a same-host setup. The item shape matches HAI's generic-feed parser, but the current HAI HTTP reader performs a plain GET and does not persist or send the parsed cursor on later syncs. The initial GET returns a bounded snapshot of the most recently updated requests (100 items by default, up to 500); treat HAI ingestion as a repeatable snapshot, not incremental synchronization. HAI's safe fetcher rejects Docker Desktop's `host.docker.internal` private-network target, so the earlier Docker-to-host recipe is not supported. See [HAI integration](docs/HAI_INTEGRATION.md) for the current boundary and open HAI-side work. The feed contains request state, duration, timezone and timestamps, not contact names, messages, tokens or calendar URLs. Network allowlisting protects this endpoint; it has no separate bearer authentication. HAI must enforce source ownership and access control.

## Limits and release evidence

- Intent analysis uses local English/Dutch rules, not a general language model. It recognizes scheduling keywords, some dates and weekdays, bounded durations, explicit clock times, and common morning/afternoon/evening phrases. When a time preference is found, available slots on the requested date are ordered by closeness to it; if that time is busy, nearby business-hour alternatives are offered. It does not reliably understand arbitrary negotiation, negation, complex recurrence or travel constraints.
- WhatsApp confirmation accepts a single explicit selection or supported affirmative phrase. Questions, multiple choices, refusals and incidental numbers are not confirmations. The public choice form is available for other phrasing.
- Availability is queried during proposal generation, checked again when a contact submits a public booking choice, and rechecked immediately before event insertion. If a selected slot has become busy, the public proposal stays open so the contact can choose another offered time. Missing or invalid calendar data stops booking. Google does not hold the slot between the final check and insertion, so another calendar writer can still create a conflict in that small interval.
- The public booking and completion pages reflect whether automatic booking is enabled, paused, completed, or awaiting operator action. A WhatsApp confirmation warning is not reported as a sent confirmation.
- Only one configured calendar/workspace/operator is supported. There is no team authorization, multi-calendar intersection, billing, SSO, general import, or end-user rescheduling flow.
- For Business API messages, signed WhatsApp status callbacks are stored idempotently and the latest provider-reported sent/delivered/read/failed/deleted state appears in the request detail. Receipt records omit recipient IDs and raw payloads, follow the configured retention window, and are included in contact export/deletion. Absence of a callback is not proof of delivery; status receipts do not automatically retry, confirm bookings, or affect the personal assisted flow.
- Contact metadata and scheduling timestamps are not all field-encrypted. Use protected local storage and backups. Retention purging is not a complete deletion policy for every domain table; use explicit privacy operations as appropriate.
- Source declarations identify the project license as Proprietary. Repository visibility alone is not permission to redistribute it.

Historical Windows, Docker, browser and benchmark results are recorded in [final verification](docs/FINAL_VERIFICATION_REPORT.md) and [performance](docs/PERFORMANCE.md). Those measurements are dated evidence, not guarantees for a new deployment. Real Meta/Google acceptance remains a separate operator step. Run the current suite with `python -m pytest -q`; run `python -m scripts.benchmark --records 1000 --reads 500` for a local baseline. Package with `windows/Build-Windows.ps1`, then smoke-test with `windows/Test-Package.ps1`. GitHub CI verifies tests, compilation, dependencies and Docker; the Windows workflow builds and tests the executable.

For maintenance and contributions, inspect [technical audit](docs/TECHNICAL_AUDIT.md), [API audit](docs/API_USAGE_AUDIT.md), [UI audit](docs/UI_ACTION_AUDIT.md), [maintenance](docs/MAINTENANCE.md), [troubleshooting](docs/TROUBLESHOOTING.md), [worklog](docs/CODEX_WORKLOG.md), [checkpoints](docs/CODEX_CHECKPOINTS.md), [task graph](docs/TASK_GRAPH.md), and [changelog](CHANGELOG.md). Add regression coverage for scheduling behavior, keep provider fakes in tests, and update the operational documentation when interfaces or setup change.
