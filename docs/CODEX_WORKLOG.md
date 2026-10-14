# Codex worklog

## 2026-10-14 - Reject OAuth callbacks without a session state

- App-wide OAuth review found that the callback compared the query state directly to `session.pop(..., None)`. With both values absent, `None == None` passed and a supplied authorization code reached the token-exchange adapter. The callback now requires non-empty query and session states and uses `secrets.compare_digest`; state remains single-use.
- Added regression coverage for missing query state, unsolicited state without an initiating session, invalid state, valid exchange, and OAuth denial. Also asserted that the connect endpoint rejects unauthenticated requests. The pre-fix missing-state test failed by reaching code exchange; the five focused OAuth tests pass.
- Full suite: 263 passed in 746.17 seconds; `compileall`, `pip check`, and `git diff --check` passed. Fresh Windows 11 x64 standalone build and isolated package smoke passed migration, three encrypted-field rotations, default backup creation, health, and branded login (67.4 MiB working set; ZIP SHA-256 `1AFA0AE3CC6E74D5339974E26ED6E691D03D22582751E2B99661E8DB1BB67E55`).

## 2026-10-14 - Fix UI contrast and private-page metadata

- A local synthetic-provider browser rehearsal exercised sign-in, the assisted personal-WhatsApp analysis/review path, the manual-share confirmation, anonymous booking-link access, consent, and recorded slot selection. The browser console was clean and the observed HTML/CSS requests returned 200. No real provider or WhatsApp link was opened.
- Mobile Lighthouse identified a WCAG contrast failure for the small amber provider-status text (4.14:1 on white) and missing page description. Darkened the shared amber token to exceed 4.5:1 on white and the amber notice background, and added a generic description plus `noindex, nofollow` to the shared template so tokenized booking pages are not offered for indexing.
- Added regressions for the amber contrast ratio and metadata on login and booking pages. Focused tests pass; full suite: 260 passed in 148.03 seconds. Mobile Lighthouse snapshot: accessibility, best-practices, SEO, and agentic-browsing all 100, zero failed audits. At 375×812 emulation, document scroll width equals the viewport width; no visual baseline exists, so this is not a visual-regression pass. No live Hetzner or provider action was performed.

## 2026-10-14 - Resume WhatsApp webhook messages after transient failures

- Reproduced a delivery-loss bug: after a signed webhook persisted an inbound message, a transient intent-analysis failure returned an error; the provider retry was then treated as a completed duplicate, so no scheduling request or proposal was created. A second injected failure after request persistence also showed that replay needed to avoid the unique source-message constraint.
- Added durable inbound processing states and a five-minute processing lease. Provider retries replay only the encrypted stored message body; completed IDs remain idempotent, stale or explicitly released work can resume, and a concurrent retry receives HTTP 503 rather than a false success. Recovery reuses an existing detected request instead of inserting a duplicate. The schema migration treats pre-existing messages as completed to avoid replaying old traffic.
- Regression tests cover transient analysis failure, failure after request persistence, and a duplicate delivered during active processing. The complete suite passes: 258 tests in 42.47 seconds. `compileall`, `pip check`, and `git diff --check` pass. A fresh Windows 11 x64 package smoke passed schema migration, encryption rotation, persistent default backup, health, and branded login (67.5 MiB working set); ZIP SHA-256 `9AF9D77CD949B229422B08EAEEF0FF16537EFF46434B6AD8B5CB4300C3F2A21B`. The durable completion state adds one SQLite commit on a normally processed webhook (five total in the critical-path trace); this is an explicit reliability cost, not a performance improvement. Hetzner remains the hosting target; no ngrok or live infrastructure/provider action was used.

## 2026-10-14 - Combine contact and scheduling-request writes

- Profiling showed transaction commits dominate the synthetic write workload. The automatic webhook path still persists a contact before intent classification; once scheduling intent is known, it now updates detected language/profile details and creates the request plus `request.detected` audit in one transaction, eliminating a separate contact-update commit. The personal-assisted path and synthetic benchmark create the contact, request, and audit in one transaction. Contact upserts without a newly detected language now preserve the existing EN/NL setting instead of silently resetting it to English.
- Added success, audit-failure rollback, retained-language, and exact webhook commit-count regressions. Interleaved baseline/variant throughput ranges overlap (baseline 66.7–120.3; combined 34.1–138.5 records/sec on this noisy host); no speedup is claimed. Structural commit count is reduced from two to one for the benchmark/assisted contact-request pair, and the automatic request path combines its contact update with request/audit.
- Full suite: 255 passed with warnings treated as errors; `compileall`, `pip check`, and `git diff --check` passed. Fresh Windows 11 x64 package smoke passed migration, encryption rotation, default backup, health, and branded login (67.1 MiB working set); ZIP SHA-256 `B1DFBD0FCE8BC3B991CE1AD76EF95954696F54BB75F0E4722770DF561611A701`. Exact-head hosted checks are pending.

## 2026-10-14 - Make SQLite restore recover corrupt databases safely

- Reproduced two restore failure modes: the CLI booted the app before dispatching restore, so an unreadable live database failed during app startup; and a zero-byte WAL held by an idle SQLite connection bypassed the old non-empty-WAL check, reaching Windows `os.replace` and failing with `PermissionError`.
- Restore now runs before app initialization, preserves unreadable/incompatible live database bytes in a timestamped safety file, and fails closed if either WAL or SHM sidecar exists. Updated operator, README, and Hetzner recovery instructions.
- Focused database CLI suite: 14 passed, including corrupt-live recovery and idle-open WAL refusal. Full suite: 248 passed with warnings treated as errors; `compileall`, `pip check`, and `git diff --check` passed. Fresh Windows 11 x64 package smoke passed migration, encryption rotation, default backup, health, and branded login (66.8 MiB working set); ZIP SHA-256 `FE396F50CAC38D8B4B3C7F507DB1430BAECBCF5A2E2D511BD52A96A4D3377031`. These are local synthetic-data checks; exact-head CI and CodeQL are pending, and no Hetzner host or real provider was accessed.

## 2026-10-14 - Keep default backups on the persistent data volume

- The CLI previously wrote its default backup relative to the process working directory. In Docker that is `/app`, while Compose persists only `/app/data`, so a successful backup could disappear when the container is replaced. The default now writes to `backups/` beside the configured database; explicit `--output` destinations remain unchanged.
- Updated the Hetzner and operator instructions to distinguish a persistent on-host backup from the separately configured encrypted off-host backup schedule. Added a regression test for the configured-database-relative path and extended the Windows package smoke to require the packaged command to create its default backup in the data directory.
- Current local verification: Python suite `242 passed`; Windows 11 x64 package built with Python 3.13.14/PyInstaller 6.22.0 (ZIP SHA-256 `20C34F1532648EBC576CB7930473B45E217DD3D6206016DA67D13C30E7E56D7C`); packaged migration, three-field encryption rotation, default backup, health, and branded login passed (67.1 MiB working set). Synthetic local data only; no provider or Hetzner host was accessed. These checks are local and do not imply hosted CI or deployment acceptance.

## 2026-10-14 - Normalize support-bundle collision errors across platforms

- GitHub Actions on Linux exposed that an existing archive was preserved but `FileExistsError` rendered as `File exists`, failing an assertion expecting the stable operator wording `already exists`. Reproduced locally by injecting POSIX errno 17, then normalized the message without changing atomic no-overwrite behavior.
- The focused support-bundle and backup no-overwrite tests pass. Full suite and exact-head hosted checks are pending.

## 2026-10-14 - Reconcile ambiguous Calendar creates and repair reminder retries

- Reproduced provider response loss after the fake Calendar had accepted an event, and a local `mark_booked` failure after Calendar creation. Both previously persisted a retryable `failed` state; the next attempt could create a second event. They now transition atomically to `manual_required` with a redacted reason, and an operator reconciliation verifies the deterministic event before marking it booked.
- Reproduced reminder-job persistence failure after the appointment was booked. An idempotent booking retry returned early and left the reminder missing; retries now ensure the reminder job without re-creating the Calendar event or re-sending the confirmation.
- Added regression coverage for both ambiguous booking failure modes and reminder recovery. Full local suite: 241 passed with warnings treated as errors; `compileall`, `pip check`, and `git diff --check` passed. Fresh standalone Windows 11 package smoke also passed migration, three-field encryption rotation, health, and login; peak idle working set was 67.4 MiB. No real Google/WhatsApp provider or Hetzner environment was accessed.

## 2026-10-14 - Replace ngrok deployment assumptions with Hetzner

- Removed the Windows ngrok start/stop scripts, process-identity helper, sample configuration, and active README/acceptance references. Historical test reports remain labeled as prior evidence, not a current supported deployment path.
- Added `docs/HETZNER_DEPLOYMENT.md` for a single-host Docker Compose + host Caddy architecture, DNS/TLS, restrictive network exposure, secrets, local-to-cloud data migration, backups, upgrades, rollback, and explicit live-acceptance gates. Replaced the combined Windows/ngrok guide with `docs/WINDOWS.md` for local standalone use.
- Made support-bundle publishing atomic and no-overwrite, with a regression test proving an existing archive remains unchanged.
- Local verification: full Python suite 236 passed with warnings treated as errors; `compileall`, `pip check`, `git diff --check`, and the PowerShell source-launcher identity/recovery self-check passed. No Hetzner server, DNS, firewall, TLS, Google OAuth, WhatsApp, HAI, or production data was accessed or changed.

## 2026-10-14 - Stabilize standalone paths for personal WhatsApp setup

- The personal WhatsApp workflow already provides local paste-and-review, Google availability, a manually shared booking link, consented slot choice, and a manual confirmation draft. It does not read a personal inbox or send personal messages.
- Found that the source launcher sets the working directory, but a packaged executable launched from a shortcut could otherwise search for `.env` and relative database/Google paths under the shortcut's unrelated working folder. Runtime configuration now anchors these paths to the source/package root and preserves explicit absolute paths.
- Added frozen-root, relative/absolute-path, and explicit `.env`-location regression tests. Full local suite: 160 passed with warnings treated as errors; compileall and `pip check` passed. Pushed as `20f29cf`; GitHub CI and Windows packaging are queued. No Google OAuth, personal WhatsApp, or public ngrok action was performed.

## 2026-10-14 - Close same-origin protocol-relative redirect bypass

- Confirmed a same-host absolute `next` URL could carry a `//attacker.example` path and become an external protocol-relative redirect. The same shared helper protected login and action `Referer` redirects.
- Validate absolute-URL paths before returning them; reject protocol-relative paths, backslashes, and controls while preserving a safe same-origin redirect. Added login and authenticated action regression coverage and updated the acceptance/security docs.
- Pre-fix regression reproduced `Location: //attacker.example/steal`; focused security/privacy suite passed after the fix (38 tests). Full suite and CI are pending.

## 2026-10-14 - Ship offline encryption-key rotation for standalone installs

- Added a non-overwriting rotation bundle command for the encrypted SQLite fields and Google OAuth token file. It validates the source schema, SQLite integrity/foreign keys, every migrated value under the new key, and the token JSON before atomically publishing a new output directory; the source files stay unchanged.
- Added strict decryption for migration use, bounded 256-row batches and streaming database hashing to limit memory, environment-only key inputs, and command dispatch through the frozen Windows executable. Updated the security, operator, README, and acceptance docs; vault-managed rotation remains out of scope.
- `python -m pytest -q -W error`: 151 passed; `compileall`, `pip check`, `git diff --check`, PowerShell parsing, local Windows package build, packaged rotation/migration command, and packaged health/login smoke passed. The package smoke rotated an empty disposable database (0 records); unit coverage re-encrypted all three database fields plus an OAuth token fixture and verified failure leaves inputs unchanged.
- No production database, credentials, provider, or public tunnel was used. Live provider/deployment acceptance remains open.

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

## Responsive request-detail accessibility — 2026-10-14

- Fresh browser QA at a 390px mobile viewport showed the scheduling page selected a request in the URL but CSS hid `.detail-rail` below 1180px. This made request details, the personal WhatsApp confirmation draft, and cancel/reconciliation controls unreachable on narrow screens.
- Changed the responsive layout to render the detail rail below the queue. A synthetic browser walkthrough now reaches the assisted flow, shares the private link only after operator confirmation, confirms a slot with consent, books through a fake Calendar, and displays the manual personal-confirmation draft. The rendered page is 390px wide with no document-level horizontal overflow; the nav retains its intentional horizontal scroll.
- Added a regression check for the responsive breakpoint. UI QA used a fresh local test database and fake providers only; it did not access personal WhatsApp, Google, ngrok, or HAI. Full suite: 142 passed in 215.07s; `compileall`, `pip check`, and `git diff --check` passed. Exact-head Windows packaging has now passed; the general CI run remains queued, as recorded below.

## Windows standalone verification — source `5e494718` — 2026-10-14

- Built the current Windows 11 x64 package into an isolated temporary output directory, leaving the repository's existing `dist` package untouched. The ZIP SHA-256 was `CDD8CAEA02396C0C835A69DD518FEE9ADFCB6DE25CD6FC89C7679F256487D40B`.
- Ran `windows/Test-Package.ps1` against that executable on loopback port 5191 with a fresh disposable database: health `true`, development mode, branded login HTTP 200, 66.1 MiB measured working set. The application process was stopped by the smoke script afterward.
- The exact-head hosted Windows package workflow `38494863561` passed dependency audits, all 142 tests, PowerShell runtime checks, package build, package smoke test, and artifact upload. The separate Ubuntu CI run `38494863543` remained queued at the time of this checkpoint.
- No real Google, Meta/WhatsApp, ngrok, HAI, or customer data was used. Local smoke-test artifacts are in unique system-temp folders; they are not part of the repository or product data.

## Calendar retry identity follow-up — 2026-10-14

- Fixed a retry loop in which Google Calendar could continue returning 409 for a deterministic event ID after the corresponding event was cancelled/tombstoned, even after read-only reconciliation marked the appointment retryable.
- Added migrations 7–8 for a persisted booking-attempt counter. Existing `booking`, `booked`, `manual_required`, and `failed` appointments retain attempt 1 and therefore their original lookup ID; new attempts increment atomically when claimed. Same-attempt retries stay idempotent, while an explicit retry after no-event reconciliation gets a distinct deterministic ID.
- Regression coverage verifies v6 data backfill, first-attempt ID compatibility, distinct retry IDs, Calendar 409 handling, and the stale reconciliation → explicit retry state path. Targeted tests: `27 passed`; full suite: `145 passed in 160.10s`. `compileall`, `pip check`, and `git diff --check` passed; Ruff is unavailable in this local venv.
- Google Calendar API guidance says IDs must be unique per calendar and recommends generating a new ID for a new instance after a 409 duplicate. Local Calendar behavior is mocked; no Google account or live Calendar was used.
- Hosted exact-commit workflows, standalone rebuild, and provider acceptance remain pending for this follow-up.

## Personal confirmation audit correctness — 2026-10-14

- The rendered assisted-booking audit showed `confirmation.send_failed` even though personal WhatsApp sends are intentionally prohibited. The old service path called the guarded send routine, treated its expected refusal as a delivery failure, and then emitted a generic warning.
- Booking now skips the send routine entirely for assisted personal records, emits an explicit `confirmation.manual_required` audit event with `automatic_send=false`, and returns an instruction to manually send the existing confirmation draft. Business API delivery/error handling is unchanged.
- A regression replaces the automatic send routine with an assertion failure, proves it is never invoked for the personal path, and verifies that the audit never labels the intentional manual follow-up as a send failure. Targeted assisted and booking tests passed; full suite: `145 passed`. The browser-level content was observed before the fix, with backend post-fix behavior verified by tests.

## SQLite close contention fix — 2026-10-14

- Exact-head Linux CI failed `test_rate_limit_reservation_is_atomic`: concurrent worker threads completed rate reservations, then `Store.close()` ran `PRAGMA optimize` on each thread-local connection and raised `sqlite3.OperationalError: database is locked`.
- Removed the per-thread optimizer call. It was an unnecessary write-capable shutdown action and could turn otherwise successful worker operations into errors; the application uses fixed indexed queries and does not depend on optimizer-generated statistics for correctness.
- The current regression is the existing 24-way concurrent reservation/connection-close test. Focused tests: `18 passed`; full suite: `145 passed`; `compileall`, `pip check`, and `git diff --check` passed. Fresh Linux/Windows hosted workflows remain pending.

## Atomic request/audit persistence and assisted-flow markup — 2026-10-14

- cProfile of the repeatable SQLite workload showed 3,222 commits across its 500-record timed pass and 500-record allocation pass; `Store.create_request` inserted the request, committed, then opened another transaction for its audit event. A regression with a failing SQLite audit trigger reproduced an orphan request before the fix. Request and audit are now committed atomically, eliminating one commit per request and preventing partial persistence.
- Three serial 1,000-record benchmark runs moved from 143.9–198.3 writes/second before the change to 452.5–849.8 after; the two-pass 500-record profile now counts 2,222 commits, 31% fewer. Read/feed latency and traced Python allocation remained in similar ranges. The run-to-run variance remains high, so the throughput median is not treated as a capacity guarantee; raw values are in `.ecc/benchmarks/sqlite-request-audit-atomicity-2026-10-14.json`.
- Browser QA exercised login and the complete personal-assisted workflow using a disposable local database and fake providers. It surfaced a readonly confirmation textarea missing `id`/`name`; the field now has a stable id/name and is labelled by its section heading. The matching regression failed before and passed after the fix. Post-fix browser inspection confirmed the field identifiers and accessible name, no console errors or warnings, and no horizontal overflow at the 2,560-pixel viewport; a post-fix screenshot and mobile viewport check were not completed.
- No real WhatsApp or Google account, Calendar, HAI service, or tunnel was used. The exact pushed head `9f4eaf6f063907d8e47bad2058ae56d9981e0ee9` passed hosted Analyze (actions/python, run `38515007379`), both Verify jobs (`38515005974` and `38515011579`), CodeQL (`115691863126`), and Windows package (`38515011545`). This is repository CI/package evidence, not provider or live-operation acceptance.

## HAI connector contract revalidation — 2026-10-14

- Rechecked `Robert-Velhorst/018-HAI` `main` at `345cf356c3f4ab497568713dc994820b4ba22b10` through GitHub. `accountfeed.GenericFeed` parses the response field `cursor`; the HTTP fetcher issues a GET to the configured URL as-is, and `Registry.ingestObservedFeed` only copies the parsed cursor into its transient `SyncReport`. The HTTP path does not append a cursor query or persist a next cursor for later reads. Thus Agenda Relay's local cursor tests prove its endpoint behavior only when a caller explicitly supplies a cursor; they do not prove HAI incremental sync. Corrected the HAI guide and matrix to describe bounded-snapshot behavior and its possible record-loss boundary.
- The HAI fetcher also rejects private-network IPs after DNS resolution. Its exact loopback opt-in cannot approve `host.docker.internal`, so the prior Docker Desktop connection recipe was not valid against current HAI source. Removed that recipe and documented same-host loopback as the supported path; Docker-to-host support needs a narrow HAI-side policy change and separate end-to-end verification.
- No HAI repository code, account, feed registration, public URL, network allowlist, or live sync was changed or exercised. The cross-repository cursor/policy work remains open; local Agenda Relay feed tests are not HAI-runtime acceptance.

## Standalone startup and WhatsApp delivery validation — 2026-10-14

- App-wide branch coverage measured 80% overall; `scheduler/standalone.py` was the weakest production runtime module at 54%. A bind-failure regression reproduced a startup race: the background reminder worker ran before Waitress tried to bind the configured web port, so an instance that failed to start could still perform work.
- Standalone startup now creates/binds the Waitress server before starting its worker. A failed bind closes the app store without starting jobs; successful shutdown stops the worker, closes the server, and then closes the store. The red-before/green-after startup regression and lifecycle/config-clamp regression pass.
- The WhatsApp Cloud API adapter now rejects malformed 2xx envelopes and blank/missing provider message IDs as ambiguous delivery, preventing a proposal from being marked sent without an ID. Generic request exception details are no longer included in operator-facing errors. Regression tests cover malformed JSON/envelopes, timeout/connection/request failures, HTTP retry classification, and the service's manual-review state.
- Verification: runtime-path tests `7 passed`; WhatsApp adapter tests `18 passed`; full local suite `191 passed`; `compileall` and `git diff --check` passed. A real Waitress smoke run on an isolated test database returned `/api/health` `200` with `ok=true` and `/login` `200`; the process was then stopped. Built the Windows 11 x64 package with Python 3.13, extracted the generated ZIP, and passed `windows/Test-Package.ps1` against the extracted executable: migration/key-rotation commands ran, health was true, login was `200`, and working set was 65.8 MiB. ZIP SHA-256: `392355E296885566A671EA7932F87B8D9C46B4FCBF5398E85695B13275AF0015`. Browser QA could not attach because the configured Chrome profile was already running, and no independent browser driver is installed in the project venv; the existing Chrome session was left untouched. Ruff is unavailable locally.
- The standalone/WhatsApp slice was committed and pushed to Agenda Relay PR #13 as `9e68494`. No WhatsApp, Google Calendar, ngrok, HAI endpoint, or customer data was contacted. Live provider acceptance, deployment, accessibility audit, and cross-repository HAI cursor persistence remain open.

## Windows dotenv and recovery-test reliability — 2026-10-14

- Reproduced that PowerShell 5.1 `Set-Content -Encoding utf8` can add a BOM which `python-dotenv` then treats as part of the first environment key; the app silently missed `APP_ENV`. The source/ngrok PowerShell launchers also retained dotenv quotes and did not honor dotenv comment/escape rules.
- The app now loads `.env` with `utf-8-sig`. Both PowerShell launchers use a shared importer that delegates parsing to the repository's installed `python-dotenv`, so the app, source launcher, and ngrok launcher agree on BOM, quotes, spaces, `#`, `=`, and interpolation semantics.
- Fixed a time-dependent recovery test fixture: the selected appointment could be less than the configured 24-hour reminder offset from “now,” correctly omitting an overdue reminder and making the test flaky. The fixture now places the recovery event three days ahead, keeping the assertion focused on future-reminder restoration.
- Corrected the Windows/ngrok guide's stale Docker Desktop HAI instruction; it now says same-host loopback only because HAI rejects the resolved `host.docker.internal` private address.
- TDD/verification: Python BOM test was red before and green after; the PowerShell dotenv helper test passed under both PowerShell 7.6.5 and Windows PowerShell 5.1.26100; isolated stale-booking reminder regression passed; full suite `192 passed`; `pip check`, `compileall`, and `git diff --check` passed. No tunnel or live provider was contacted.
- The dotenv/docs/test follow-up is local pending exact-head Windows package workflow and hosted CI. Real provider/OAuth, ngrok account/domain, live HAI ingestion, and deep security review remain unverified.

## Backup and restore schema-validation hardening — 2026-10-14

- A branch-coverage-guided audit exposed that `_validate_app_database` accepted an arbitrary SQLite file containing only a `schema_migrations` table with the latest version number. It also accepted a migrated database with a missing core table or foreign-key orphans, allowing malformed files to pass the backup/restore validation boundary.
- Validation now requires the exact complete migration ledger, all migration-derived tables and expected column signatures, SQLite integrity, and a clean `PRAGMA foreign_key_check`. The expected schema is derived once from the application's migration set and cached, so validation remains aligned with migrations without rebuilding reference schema on every backup/restore.
- Regressions were confirmed red before the fix for a forged latest-only ledger, a missing core table, and foreign-key orphans; they pass after the fix. Backup and restore also explicitly reject the forged database, with a regression confirming restore leaves the live database intact.
- Verification: full local suite `196 passed`; coverage-guided run before the fix showed 81% overall branch-aware coverage (CLI 55%), which motivated this audit. `pip check`, `compileall`, `git diff --check`, and Windows PowerShell 5.1/PowerShell 7 runtime checks passed. Rebuilt and extracted the Windows 11 x64 package; `windows/Test-Package.ps1` passed with health `true`, login `200`, and 65.7 MiB working set. ZIP SHA-256: `AD4173A0F3247E94532EDD3E8EA986359B6F65AF5806B5EA0ECFB6350AFD2511`. No provider, tunnel, HAI service, or customer data was contacted; exact-head hosted CI is pending.

## Malformed worker payload isolation — 2026-10-14

- A new worker regression reproduced that a malformed or non-object `background_jobs.payload_json` raises from `Store.claim_due_jobs`, rolling back the claim batch and stopping all later due jobs from being processed.
- The claim loop now validates that each payload decodes to an object before invoking a job. A malformed row is atomically marked failed with a generic error and `job.failed` audit entry; later valid jobs in the batch remain claimable. Raw malformed data is not copied to logs or audit details.
- The regression was red before the fix and now passes for malformed JSON, an array, and a JSON string. Full local suite: `199 passed`; `pip check`, `compileall`, and `git diff --check` passed. Rebuilt and extracted the Windows 11 x64 package; `windows/Test-Package.ps1` passed with health `true`, login `200`, and 65.7 MiB working set. ZIP SHA-256: `2E2618EB6432EAA7466CA9AAB455D2EFC179E6441DD7715906DE960D280CAD7E`. No provider, tunnel, HAI service, or customer data was contacted; exact-head hosted CI is pending.

## Next-week weekday parsing — 2026-10-14

- A code-path review found that deterministic date parsing mapped every “next week” message to Monday, even when the sender explicitly named a weekday (for example, “next week on Tuesday” or “volgende week dinsdagmiddag”). This could offer times on the wrong day.
- The parser now anchors to the next Monday and applies the named weekday offset; week-only requests still resolve to Monday. Three English/Dutch regressions failed before the fix and pass afterward.
- Verification: full local suite `202 passed`; targeted intent suite `25 passed`; `pip check`, `compileall`, and `git diff --check` passed. Rebuilt the Windows 11 x64 standalone from this source and ran `windows/Test-Package.ps1`: health `true`, development mode, branded login HTTP `200`, encryption rotation succeeded, working set `65.5 MiB`. ZIP SHA-256: `D00EB622AE17E6366A69F7E3592E14801AAB0611CAB28DC0D8192EC8F5B7F4C8`. Package and test data are in a unique system-temp folder. No live provider, tunnel, HAI runtime, or personal conversation was used; hosted exact-head CI and live acceptance remain open.

## Doctor exit status includes storage — 2026-10-14

- Branch-aware coverage showed `scheduler/cli.py` at 60%. The `doctor` command reported `database.writable=false` but returned exit code 0 whenever providers were ready, so deployment scripts could accept a broken/locked database as healthy.
- Doctor now exits successfully only when both runtime readiness and the SQLite integrity/write-lock check pass. The regression was red before the fix (`0` instead of `1`) and now verifies the JSON still reports the database failure while returning nonzero. The acceptance matrix now includes this contract.
- Verification: focused CLI/database suite `9 passed`; complete suite `203 passed in 245.98s`; `pip check`, `compileall`, and `git diff --check` passed. Rebuilt the Windows 11 x64 standalone and ran `windows/Test-Package.ps1`: migrations, key rotation, health, and branded login passed; working set `66.9 MiB`. ZIP SHA-256: `1589DF8302ECAB0FB75F5EA848DE8C498E589CBDDED0F6A969AB4134AE46D679`. These checks used disposable local data; no provider, ngrok endpoint, HAI runtime, or real conversation was used.

## Recoverable Google OAuth callback — 2026-10-14

- The Calendar boundary review found that Google's normal `error=access_denied` callback was passed to `fetch_token` as though it contained an authorization code, which raised an unhandled provider exception. Other exchange failures also escaped the route and could expose a traceback in server logs.
- The callback now checks OAuth state first, treats provider denial as a recoverable cancellation, catches exchange failures with type-only logging and a generic retry message, and writes the connection audit only after exchange succeeds. Four regressions cover denial, bad state, successful exchange/audit, and sanitized failure; both new failure tests reproduced unhandled exceptions before the fix.
- Verification: Calendar safety suite `21 passed`; full suite `207 passed in 110.01s`; `pip check`, `compileall`, and `git diff --check` passed. Rebuilt the Windows 11 x64 standalone; migrations, key rotation, health, and branded login passed with `67.3 MiB` working set. ZIP SHA-256: `3DE5CC78DEC36BA6C88A33A4D7E39A2DB5771888A54BF141B22A938E38958813`. Test data remained in isolated system-temp folders; no Google account, tunnel, HAI runtime, or personal WhatsApp conversation was used.

## Backup publication preserves existing files — 2026-10-14

- A coverage-guided CLI review found that `_online_backup` used `os.replace`, so reusing an explicit output path silently destroyed the earlier backup.
- Added a regression that was red before the fix and verifies both refusal and byte-for-byte preservation. Backup publication now uses a same-directory hard link, which atomically fails when the destination already exists; temporary files are still removed by the existing cleanup path.
- Verification: focused CLI/database suite `10 passed`; full suite `234 passed`; `compileall`, `pip check`, and `git diff --check` passed on Windows. Hosted exact-head CI and package verification are pending.

## Key rotation validates the full application schema — 2026-10-14

- A forged SQLite file with only the latest migration number and the three tables/columns touched by encryption rotation passed rotation's weaker `max(version)` check and could be published as a rotation bundle despite missing most application tables.
- The regression reproduced the unsafe publication before the fix. Backup/restore and encryption rotation now share one validator requiring SQLite integrity, clean foreign keys, the exact migration ledger, and all migration-derived tables and column signatures.
- Verification: focused crypto-rotation and CLI/database suites `17 passed`; full suite `235 passed`; `compileall`, `pip check`, and `git diff --check` passed on Windows. Hosted exact-head CI and package verification are pending.

## Encrypted-field reads fail safely on malformed ciphertext — 2026-10-14

- Branch-aware coverage reported `scheduler/crypto.py` at 70%. A targeted regression reproduced unhandled `UnicodeEncodeError` for non-ASCII ciphertext text and `UnicodeDecodeError` for authenticated ciphertext containing non-UTF-8 bytes. Either could turn an operator view of corrupted/mismatched stored data into a server error.
- Non-strict display decryption now returns the existing explicit corruption marker for invalid tokens and Unicode encoding/decoding failures. Strict decryption remains fail-closed for key rotation and integrity-sensitive operations.
- Verification: focused crypto tests `4 passed`; full suite `246 passed in 174.44s` with warnings treated as errors; `compileall`, `pip check`, and `git diff --check` passed. Windows package and exact-head hosted checks are pending. No provider or production data was used.
