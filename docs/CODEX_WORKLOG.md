# Codex worklog

## 2026-10-14 - Sanitize API exceptions and verify assisted flow in browser

- Reproduced CodeQL's exception-disclosure path with a traceback-bearing HAI error. API exception handlers now return stable client-safe messages while preserving error codes and HTTP statuses; the regression proves traceback and filesystem path details are absent.
- Corrected the fake Calendar adapter to honor its requested start date and added a critical-path assertion that no proposed slot precedes that date. The assertion failed against the old fake, then passed with the corrected fixture.
- Full local suite: 116 passed. Focused HAI suite: 6 passed. Browser QA with synthetic provider fixtures verified sign-in, assisted proposal rendering, expected weekday/date/time slots, and a pre-share booking-link 404. At emulated 390px mobile, document width matched viewport; console was clean and CSS/favicon returned 200.
- Current benchmark run (1,000 records/500 reads): 497.3 writes/second, 1.386 ms dashboard p95, 4.681 ms for 500 HAI items, 0.49 MiB traced Python peak. This is one variable local sample, not a capacity guarantee or a measured optimization.
- Commits `e8b59d1` and `442fce6` are pushed to PR #13; exact-head verification, Windows package, Python/actions analysis, and CodeQL passed, with no new CodeQL alerts. No live Google, WhatsApp, HAI, or ngrok operation was attempted.

## 2026-10-14 - Lock HAI incremental cursor behavior

- Verified the HAI `json-feed` cursor watermark against the connector implementation: the initial bounded snapshot is reversed into ascending order before its newest timestamp/ID is encoded as `nextCursor`.
- Strengthened `tests/test_hai_integration.py` to assert a multi-item snapshot is not replayed when HAI returns the unchanged cursor, while a later request is delivered incrementally. This protects an existing correct invariant; no production code change was needed.
- Focused HAI tests passed (5); the full local suite passed (112).

## 2026-10-14 - Validate ngrok process ownership before stop

- Replaced PID/name-only tunnel shutdown with exact executable and command checks for the saved ngrok configuration, assigned domain, isolated inspector configuration, and loopback target.
- The start failure cleanup now uses the same ownership check; argument quoting preserves config paths containing spaces. Stop waits for confirmed exit and retains runtime state if the owned tunnel remains.
- Added self-checks for the owned tunnel, a different ngrok domain, and an unrelated ngrok executable. They passed under PowerShell 7 and Windows PowerShell 5.1; all eight Windows PowerShell scripts parsed under PowerShell 7.
- Hosted Windows CI showed the synthetic test mixed a short 8.3 path from `Join-Path` with a long normalized path in expected state. The fixture now normalizes its executable/config paths before constructing command-line arguments, matching the launcher's behavior; the verifier retains case-insensitive, boundary-aware literal matching and safe verbose diagnostics.
- No live tunnel was started: this checkout still has no `.env` or provider credentials.

## 2026-10-14 - Validate Windows launcher recovery and package

- Added exact executable/command identity validation for recorded web and worker PIDs, health-gated detection of an already-running app, safe missing-worker recovery, and fail-closed shutdown state handling.
- Added a Windows package workflow self-check for launcher identity/recovery. It passed locally under PowerShell 7 and Windows PowerShell 5.1; all Windows PowerShell scripts parsed under PowerShell 7.
- Built the standalone x64 package on Windows 11 Pro (build 26300). Package health/login smoke passed; ZIP SHA-256 `94AF076E7330E003E34544A2432C80DA29629AD02A368F1631CDAEF930A9ACE`, 32.23 MiB.
- The full Python suite passed 112 tests, `compileall` passed, and `pip check` found no broken requirements. Real Google OAuth, personal WhatsApp, HAI runtime, ngrok exposure, and target-PC acceptance remain unverified; no provider credentials or tunnel were used.
- Six serial local performance runs are now recorded in `docs/PERFORMANCE.md`. Variability is too high to justify claiming a measured optimization, so no write-path optimization was promoted.
- Exact published source SHA `01b45886928844b9c92087abad5ca6bf5407d9f9` passed push CI `38478527287`, PR CI `38478532204`, Windows package `38478532233`, and CodeQL run `38478527776`. The GitHub-hosted Windows workflow emitted a non-failing Node.js 20 deprecation advisory.

## 2026-10-13 - Keep immutable static caching safe across upgrades

- Reproduced that the app marked stable `/static/...` URLs immutable, allowing a browser to retain stale CSS after a release.
- Templates now include a 16-character SHA-256 content version for the packaged CSS and favicon. Only a matching version gets one-year immutable caching; unversioned or mismatched static URLs must revalidate.
- Added a regression that compares the rendered asset digest with the file and checks both cache policies.

## 2026-10-13 - Add reauthenticated browser contact deletion

- Closed the documented gap between the guarded contact-deletion API and the Contacts screen.
- The browser action now requires session authentication, CSRF, and current-password reauthentication; attempts are rate-limited and audit records never include the supplied password.
- Existing fail-closed appointment guard applies unchanged: active appointments must be cancelled/resolved first, and deletion never cancels a Calendar event as a side effect.
- Fixed invalid nested-form markup in the Contacts table by associating each row's edit/delete controls with separate external forms.
- Added regressions for CSRF, wrong/correct password, and refusal while a Calendar appointment remains active.

## 2026-10-13 - Prevent contact deletion from orphaning Calendar appointments

- Reproduced that `DELETE /api/contacts/<id>` removed the contact and appointment rows even when a booked Google Calendar event remained active.
- Contact deletion now fails closed with HTTP 409 while any linked appointment is not cancelled. The operator must cancel or resolve appointments first; successful deletion still removes the linked application records and leaves its minimal privacy audit event.
- A regression test exercises the full proposal -> confirmation -> Calendar booking -> refused delete -> Calendar cancellation -> successful delete path with test-only providers.
- The re-authenticated browser deletion flow remains a documented product gap; this change hardens the existing API rather than claiming that workflow is complete.

## 2026-10-13 - Prevent stale conversation intent from duplicating/changing requests

- Reproduced two defects in `SchedulingService.process_payload`: an unrelated “Thanks!” after a scheduling message created a second proposal, and a new scheduling request without a date inherited the prior request's explicit date.
- The service now analyzes only the newly received message for scheduling intent and request details. Older conversation text remains encrypted and available to the operator, but no longer implicitly triggers or alters a request. Slot-confirmation matching still runs before intent analysis.
- Regression coverage verifies unrelated follow-ups are ignored, explicit new requests still work, and a new request does not inherit a prior date. The HAI feed fixture now uses an explicit second scheduling message rather than relying on the old duplicate behavior.
- Targeted webhook/HAI/critical-path/personal tests: 40 passed. Full suite: 126 passed. A single local 1,000-record benchmark run after the prior three-run sample varied substantially on write throughput; the range and caution are recorded in `docs/PERFORMANCE.md` rather than presented as a guarantee.
- Exact-SHA CI and Windows packaging are required for every follow-up commit. Provider, ngrok, and HAI live acceptance remain unverified.
## 2026-09-23 - Recheck availability before booking

- Added a strict Google FreeBusy check for the exact contact-confirmed interval immediately before event insertion. Busy slots, provider errors, malformed responses, and missing availability fail closed before creating an event.
- A conflict marks booking for operator attention and reports that new times must be offered; it does not silently substitute another slot after the contact chose a specific time.
- The check cannot reserve the interval atomically; a separate calendar writer could still book during the short check-to-insert interval.
- Verification: all 58 local tests pass; Python compilation and `git diff --check` pass.
- Public booking now checks availability before consuming a selected proposal, keeps the link usable if the slot is busy, and reports whether calendar booking and WhatsApp confirmation actually completed. Focused public-flow checks pass.
- Hardened the optional HAI feed so forwarded headers cannot grant loopback access; requests through a loopback-bound public tunnel are denied. Added spoofed-loopback regression coverage. Full local suite remains 58 passing.
- Bound signed inbound WhatsApp messages to the configured phone-number ID so messages from another number subscribed to the same Meta app are ignored; added a regression test.
- Made Docker image and Compose services production-fail-closed by default, rejected short production encryption keys, and extended the Windows workflow's dependency audit to include build requirements.
- The current WhatsApp channel remains Meta Cloud API and does not support a personal WhatsApp inbox. A personal-account workflow still needs Robert's choice of a supported assisted flow or a business-number integration; unofficial web-session automation is not being added.
- Security review found that proxied login failures share the loopback rate-limit bucket, so five failed attempts can temporarily block other ngrok visitors. This remains a deployment limitation until a trustworthy per-client identity or non-lockout throttle is chosen.

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

## WhatsApp delivery-status callback follow-up — 2026-10-14

- Added storage for signed Cloud API status callbacks, including `sent`, `delivered`, `read`, `failed`, and `deleted`; callbacks are scoped to the configured phone-number ID and deduplicated by message/status/provider timestamp.
- The request detail displays the latest provider-timestamped receipt. Older/out-of-order events are retained without regressing booking state; callback processing never retries a send or marks an appointment booked.
- Only provider message ID, status, timestamp, bounded provider error code, and local receipt time are stored. Recipient IDs and raw callback bodies are excluded; events are included in contact export/deletion and retention purge.
- TDD regression tests first failed because status callbacks were ignored. Follow-up tests cover signed status-only payloads, phone-number mismatch, malformed status/time, duplicates, ordering, UI display, PII minimization, export/deletion, and retention.
- Regression proof: new tests failed first because delivery callbacks were ignored; after implementation, the full suite passed 115 tests. `compileall`, `pip check`, and `git diff --check` passed. Local Ruff is not installed in this venv; hosted analysis and CI gates passed for source commit `5374b1b786575173998a8dacf131f5ccd17fbe46`.
- Rebuilt and smoke-tested the standalone executable on Windows 11 Pro build 26300: health true, development mode, login HTTP 200, 66.1 MiB working set. ZIP SHA-256: `365E3258E1E258550012B297936B7420810B2CF81CFC1AFA67350A34CBFEDF92`.
- Real Meta callback delivery/subscription remains an external provider acceptance step; no live webhook or customer data was used.
- Exact source SHA `5374b1b786575173998a8dacf131f5ccd17fbe46` passed PR verification `38483821835`, push verification `38483815562`, Windows package `38483821965`, Actions/Python analysis `38483817822`, and CodeQL run `115592808146`.

## Exact appointment-job association follow-up — 2026-10-14

- App-wide review found that appointment cancellation and contact deletion used a JSON substring match on numeric IDs. For example, appointment `1` could match jobs for appointment `10`; cancellation could stop the wrong reminder and privacy deletion could erase unrelated background jobs.
- Centralized candidate lookup: narrow by workspace and optional type/status, then parse each payload and compare an exact integer ID. Cancellation keeps its reminder-only/state guard. Contact deletion removes all job types tied to the exact deleted appointment and preserves same-prefix and other-workspace jobs.
- Regression evidence: targeted cancellation and contact-export/deletion tests pass (2 passed); full local suite passes (130 passed); `compileall`, `pip check`, and `git diff --check` pass. GitHub package workflow for the previous pushed commit has not yet completed; this follow-up is not yet pushed at this checkpoint.
- Provider, HAI, tunnel, and hosted acceptance remain outside this local regression.

## Transactional booking and cancellation follow-up — 2026-10-14

- Critical-path review found that request-state changes and their audit entries were committed separately from appointment/proposal mutations. A process or database failure in between could leave the dashboard states inconsistent. Cancellation could also change an appointment already in `booking`, allowing late calendar completion to race with cancellation.
- Added a transaction-scoped request transition helper that writes the state and audit atomically. Applied it to proposal send/manual-share/confirmation, booking claim/completion/failure, and appointment cancellation. Calendar cancellation now refuses an in-flight booking with an authenticated API `409`; completion requires the appointment still be in `booking`. Actor identity is carried through the booking claim and failure transitions.
- Regression evidence: the race test checks that cancellation is refused mid-flight and injects an SQLite audit insert failure to prove the appointment and request both roll back; it then verifies a successful completion. Full suite: 131 passed. `compileall`, `pip check`, and `git diff --check` pass. This follow-up is local at this checkpoint and requires current-head hosted CI/package validation after push.
- Extended the same atomic transition path to proposal creation, expiry, delivery reconciliation, and stale-booking recovery. Stale recovery now commits its appointment `manual_required` state, `booking_pending -> failed` request transition, and audits together; a regression verifies both resulting state records.
- Final local verification for the expanded transaction/recovery changes: 132 tests passed; `compileall`, `pip check`, and `git diff --check` passed. `pip-audit` is not installed in this venv; the exact-commit hosted audit/package workflow is still required.

## Stale Calendar booking reconciliation — 2026-10-14

- Added a session/CSRF-protected dashboard action and bearer-authenticated API endpoint to reconcile appointments left `manual_required` after a stale booking claim.
- Google Calendar lookup is read-only and validates the deterministic event ID, confirmed status, private appointment marker, and exact timezone-aware interval. A match atomically restores appointment/request state and audit history; an absent event becomes an explicitly retryable failure. Errors or mismatches preserve manual review.
- Recovery sends no WhatsApp confirmation. Business reminder scheduling is restored only after a verified event; personal assisted-flow communication remains manual.
- Focused tests passed for matching/absent/mismatched provider events, sanitized lookup errors, retry path, CSRF, and no-send behavior. Full suite and exact-commit hosted checks remain to be run.
