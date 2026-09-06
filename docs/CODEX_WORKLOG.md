# Codex worklog

## 2026-09-07 - Local executable and setup improvement

- Added `AgendaRelay.exe --setup` and `python -m scheduler.cli setup` to create an operator password hash and independent random secrets without overwriting existing settings.
- Reproduced and fixed false confirmations from negative, ambiguous, or incidental numbered replies (nine regression cases).
- Reproduced and fixed missing Google availability being treated as a free calendar (three response-shape regression cases).
- Fixed end-of-business-hour 24 handling and skipped expired daily availability windows.
- Expanded README setup, configuration, architecture, operations, and limitations.
- Verified 53 tests passed, rebuilt the Windows executable, checked `--help`, and passed executable health/login smoke checks at 65.4 MiB working set. ZIP CRC and repository README links passed.
- Current local provider readiness remains false: Google OAuth, Meta access token/phone ID, and local operator password configuration are missing. HAI remains disabled. No live-provider actions were performed.
- Publication is tracked by Git history and the matching pull-request checks; earlier published CI results do not validate this revision.

## 2026-07-25 - Initial MVP

Created the small approval-first Flask MVP from an empty repository/supplied flat archive. Added HMAC, deduplication, deterministic intent, FreeBusy, proposal approval, Windows timezone support, and four tests.

## 2026-08-08 - Giant prompt implementation

- Rendered and inspected all 124 PDF pages; extracted phases 000-115 and final response requirements.
- Initialized local Git `main` with the supplied GitHub URL as origin; starting branch was unborn.
- Preserved official webhook/FreeBusy behavior and replaced the prototype persistence/orchestration with explicit domain state.
- Added workspace ownership, encrypted message/token fields, contacts/consent, requests, proposals, appointments, jobs, audit/rate/system state, and forward migrations.
- Implemented WhatsApp reply/private-link confirmation, Google event creation/cancellation, reminders, pause, rate limit, privacy, retention, backup/restore/doctor/support commands.
- Designed and implemented the authenticated operator dashboard and public booking UI.
- Added production startup guards, security headers, session/CSRF security, Docker/worker, CI, locked dependencies, tests, and required documentation.
- Automated verification passed after correcting a Jinja dictionary-method collision in the queue template.

Checkpoint at that time: browser QA, Docker/config checks, final reports/publication, and real-provider gates remained. The next entry records their current state.

## 2026-08-09 - Windows, HAI, performance, and release hardening

- Added a self-contained Windows executable and source install/start/stop scripts, then smoke-tested health, branded login, resource use, and shutdown.
- Added a guarded ngrok launcher with production/readiness checks, exact-domain verification, and an isolated inspector config that does not disturb existing tunnels.
- Added a loopback/CIDR-restricted, cursor-based, metadata-minimized HAI `json-feed` connector and regression coverage.
- Moved SQLite to thread-local persistent WAL connections, added query indexes, bounded feed/pagination work, and recorded a repeatable 1,000-record performance baseline.
- Fixed booking-link activation expiry, Windows port collision handling, package spec/CI defects, and a 181 MiB irrelevant Docker context.
- Reverified 25 tests, locked dependency consistency, live vulnerability audit, Docker non-root health, unsafe-production refusal, and the Windows package.

## 2026-08-09 - Final adversarial hardening

- Closed open-redirect, public booking CSRF, and CSV spreadsheet-formula injection paths.
- Made outbound and HAI rate reservations atomic and added atomic proposal-send and confirmation claims.
- Distinguished verified-rejected WhatsApp calls from ambiguous network delivery; only verified-safe failures can be resent.
- Added crash recovery for stale jobs, proposal sends, and calendar bookings, plus idempotent Google 404 cancellation and atomic OAuth token replacement.
- Preserved contact timezones throughout proposals, private booking, confirmations, and reminders; rejected expired WhatsApp confirmations.
- Expanded the automated suite from 25 to 37 tests, including real SQLite contention checks.

Remaining external gate: authorized Meta/Google credentials and approvals, a stable available ngrok endpoint, and real-provider acceptance/cleanup.
