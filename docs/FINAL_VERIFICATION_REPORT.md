# Final verification report - 1.0.0

Date: 2026-08-09

## Passed locally

- Python compilation and dependency consistency: passed.
- Automated suite: 37 passed, including concurrent SQLite send, confirmation, and rate-limit tests.
- Dependency vulnerability audit: no known vulnerabilities in the exact commit's two Linux CI runs and Windows package run.
- PowerShell syntax: all Windows launch/build/test scripts parsed successfully.
- Windows source runtime: installer, web/worker start, health response, resource readout, and exact-process stop passed.
- Windows packaged runtime: health 200, branded login 200, 65.5 MiB idle working set, and exact-process shutdown passed.
- Windows ZIP: 1,315 entries, CRC check clean, executable and README present.
- ZIP SHA-256: `08163085D541B8B83A71D3A2160B8A8E0F345B6B4106FF176955F7153458AAC7`.
- Docker: configuration valid; final hardened image built from a 249.13 KiB context with package artifacts excluded, ran as uid/gid 10001 `agenda`, returned health 200, and refused unsafe production configuration with exit code 1.
- Browser: desktop and mobile operator flows rendered and interacted successfully with no console warnings/errors.
- Performance: established 1,000-record baseline remains 601.5 records/second with 4.792 ms median dashboard reads. A final contention-heavy 500-record rerun measured 3.036 ms median, 4.799 ms p95, a 10.763 ms 500-item HAI page, and 0.64 MiB peak Python allocation.
- Repository truth scan: no private-key/token signatures or encoding corruption; runtime secrets/data/build outputs are ignored.
- Publication: hardened commit `21c6976` is pushed to draft PR #1 against `main`; both independent Linux CI checks passed on that exact SHA.
- Final Windows GitHub Actions package run `31288093704` passed in 1m33s. It ran all 37 tests, audited dependencies, built and launch-tested the executable, and uploaded the 33,136,022-byte `AgendaRelay-Windows-x64` artifact with GitHub digest `sha256:816349fa6fc2c15bf43731528b25a4b10ec1d250ccd1bd475c3a9a72f0332399`.

## Provider/account gate

No real WhatsApp message or Google Calendar event was created during release verification. A temporary isolated ngrok agent reached the cloud service, but the account's free endpoint was already online elsewhere and ngrok returned `ERR_NGROK_334`. Agenda Relay did not enable endpoint pooling or disturb that existing tunnel. Live production acceptance therefore still requires authorized Meta and Google credentials/approvals plus an assigned available ngrok domain/session.

This distinction is intentional: local build/test/package readiness is verified; real-provider production operation is not claimed without owner-authorized accounts and cleanup.

## Current branch verification addendum — 2026-09-23

These checks apply to the current branch after the hardening changes; they supplement, and do not rewrite, the historical 2026-08-09 results above.

- Current Python test suite: 60 passed.
- Windows standalone package: rebuilt locally; ZIP SHA-256 `8A1999C2A72ED0E485D00A67C64F71A73573BCB7F7C7D4341B9F4A39C9E30662`.
- Isolated packaged-app smoke test: health response reported `ok: true`, the branded operator-login page returned HTTP 200, and a test-only operator session reached the dashboard. A reversible pause/resume control check succeeded. Test database and configuration were kept in a temporary directory; no live provider credentials were used.
- Browser-visible readiness correctly reported that WhatsApp Cloud API credentials and Google Calendar OAuth were not configured. No WhatsApp message or Google Calendar event was sent or created.
- Fresh performance measurements are recorded in [PERFORMANCE.md](PERFORMANCE.md); they are single-host observations, not deployment guarantees.
- The open draft PR's current source commit at the start of this addendum was `98007a0f18ce222cef5290e071290b8ef6badb27`; its two CI checks and Windows package check were successful. This source-check result is point-in-time and precedes this documentation-only addendum.

## Current branch verification addendum — 2026-10-13

These checks apply to the current branch after the scheduling, calendar-query, and Windows package-script changes.

- Scheduling-language regression: English “next week” / “following week” and Dutch “volgende week” / “komende week” now resolve to the next Monday. Regression tests cover the English and Dutch forms.
- Calendar availability regression: the 21-day search now makes one batched FreeBusy request. The deterministic test confirms the previous per-day approach made 11 calls in its scenario and the new implementation makes one; event creation still has a separate final availability check.
- Python test suite: 63 passed. `pip check`, `compileall`, and `git diff --check` passed.
- Windows package: built on Windows 11 with Python 3.13.14 through `windows/Build-Windows.ps1` using explicit temporary output/work directories. ZIP SHA-256: `6DB165EF617B855BD7C591314E8F50B875BCA2A4D794CC9E87B5A4CAF1854751`.
- Packaged-app smoke test: `windows/Test-Package.ps1` reported health `ok: true`, development mode, branded login HTTP 200, and 67.4 MiB working set. It ran with provider credentials cleared, automation paused, test-only secrets, and a temporary database/log directory; the repository's existing `data` and `dist` were not used as test state.
- Synthetic webhook check: a locally signed scheduling webhook was accepted and persisted with requested date `2026-10-19`. Processing then stopped at the expected missing-Google-OAuth gate; no Calendar query/event or WhatsApp message was made.
- Package-script note: a prior build using the default PyInstaller work directory failed on this host while writing into the repository's existing build folder. The revised script supports a unique temporary work path; the isolated invocation above passed.
- Product boundary: this repository still integrates with WhatsApp Business Cloud API only. It does not connect to a personal WhatsApp inbox. The opt-in WhatsApp Agent Platform is a separate feature and cannot access a user's other chats, per the [WhatsApp Help Center](https://faq.whatsapp.com/1050934623978152). No real WhatsApp or Google Calendar operation was verified.
- Publication: these changes are pending commit/push and CI verification; no claim is made here that this addendum or code has reached GitHub.
- Dependency-audit follow-up: the first push-triggered CI run stopped at `pip-audit` before compilation/tests because the lock contained vulnerable `oauthlib 3.3.1`, `urllib3 2.7.0`, and `Werkzeug 3.1.8`. The runtime requirements and lock now pin the audited fixes (`4.0.0`, `2.8.0`, and `3.1.9`). Local `pip-audit -r requirements.lock` reports no known vulnerabilities, `pip check` passes, and all 63 tests pass with those versions. GitHub CI for this follow-up commit is still pending at the time of this report.

## Subsequent follow-up — OAuth bootstrap and resume safety — 2026-10-13

This later update supersedes the pending publication/CI statements above for the branch state identified here.

- Fixed the Google OAuth/ngrok bootstrap deadlock. A protected operator-readiness response now distinguishes safe public ingress from full scheduling readiness. Public ingress requires valid production configuration and WhatsApp credentials; with Google OAuth disconnected, it is allowed only while automation is paused. The Windows launcher checks that response locally using the operator bearer token; it never sends that token through ngrok.
- Prevented the dashboard resume action from enabling automation while production validation or either provider is unready. The operator receives the configuration/provider blockers, and the pause remains on.
- Regression coverage proves the ingress rule, API authentication boundary, and resume guard. Current full suite: 66 passed. `pip check`, `pip-audit -r requirements.lock`, `compileall`, `git diff --check`, and PowerShell parsing of all `windows/*.ps1` passed.
- GitHub push CI run `38370672877` passed on commit `0a3d9fa7d61c68cc38640e577fa888b22f517101` (dependency audit, compilation, tests, Docker build).
- Browser QA limitation: the attached Chrome DevTools instance refused a new tab because its profile was already in use; an isolated Browserbase session could not reach the local `127.0.0.1` test server (`ERR_CONNECTION_REFUSED`). The changed operator behavior was verified with Flask's test client, but no fresh browser screenshot/console audit is claimed.
- No ngrok tunnel or live provider action was run. The actual public HTTPS callback, Google consent, Meta webhook delivery, personal WhatsApp, and real calendar event path remain unverified. Follow-up commits `2fd92d5`, `27c4b73`, and `0a3d9fa` were pushed to the existing branch after PR #1 had already merged; they are not part of that earlier merge.

## Performance measurement correction — 2026-10-13

- `scripts/benchmark.py` no longer runs `tracemalloc` during timed writes/reads. It performs a separate allocation pass so instrumentation overhead cannot distort the latency numbers.
- Three local 1,000-record/500-read runs measured 874–1,171 writes/second, 0.554–1.113 ms dashboard median, 0.593–1.769 ms dashboard p95, 4.551–7.680 ms for a 500-item HAI feed, and 0.48 MiB traced Python peak allocation. Repeat-run spread is reported rather than hidden; these are single-machine measurements, not deployment guarantees.
- The earlier 2026-08 and 2026-09 figures remain historical results from the instrumented benchmark and are not directly comparable to this corrected method.

## Subsequent follow-up — webhook payload resilience — 2026-10-13

- Hardened the signed WhatsApp webhook parser against malformed top-level and nested JSON shapes, invalid message field types, and malformed optional contacts. Invalid message events are acknowledged as ignored; valid messages continue to process when optional contact details are malformed.
- Out-of-range message timestamps now safely fall back to the current UTC receipt time rather than raising an overflow error.
- Full local suite: 79 passed. `compileall`, `pip check`, and `git diff --check` passed.
- The targeted Codex Security diff scan (`e205d912-37ed-40c7-a711-cea6325d9ecb`) completed with no reportable findings for this patch. It reviewed the changed parser and tests plus the signature-verifying route; it was not a full repository security audit.
- At the time this addendum was first written, the code had not yet been pushed. The webhook-resilience code was subsequently pushed to `agent/agenda-relay-production` as commit `afd170f88a4df4136b03d58ea28e3e529b04bbb9`; its GitHub CI run `38373387020` is queued and has not started, so no CI result is claimed.

## Packaged-app UI verification — 2026-10-13

- Rebuilt the Windows x64 standalone package from commit `afd170f88a4df4136b03d58ea28e3e529b04bbb9` in an isolated temporary directory. ZIP SHA-256: `F45886E595FBF2784179436B4B0262D33EC2D60D72F450B67FC2527591C24B4A`.
- `windows/Test-Package.ps1` passed against the extracted package: health `ok: true`, development mode, branded login HTTP 200, and 67.5 MiB working set. Test configuration, database, and logs were isolated; provider credentials were absent and automation was paused.
- A localhost browser check signed in with a test-only password, rendered the scheduling dashboard, and navigated to the Scheduling view. The browser reported no console warnings or errors. Provider readiness correctly showed WhatsApp Cloud API and Google Calendar as unconfigured. No real message or calendar event was sent or created.
- The package and UI checks are local evidence only. GitHub CI run `38373387020`, for the same code commit, remains queued without a runner; its outcome is pending. The branch tip and `origin/agent/agenda-relay-production` were both `afd170f88a4df4136b03d58ea28e3e529b04bbb9` before this report update.

## Audit endpoint limit hardening — 2026-10-13

- Authenticated `GET /api/audit?limit=-1` previously passed a negative SQLite `LIMIT`, which returns every matching audit row. The store now clamps the value to 1–500 before querying.
- An API-level regression test reproduced the unbounded response before the fix and now verifies the negative-limit request returns one row. The full local suite passes 80 tests; compilation, `pip check`, `pip-audit -r requirements.lock`, and `git diff --check` pass.
- These are local checks; GitHub CI for this follow-up is pending and will be checked against the pushed commit.

## Request pagination overflow hardening — 2026-10-13

- Authenticated `GET /api/requests?page=<1000 digits>` previously reached SQLite with an out-of-range `OFFSET` and raised `OverflowError`. The store now clamps requested pages to the filtered result set before computing the offset.
- An API-level regression reproduces the overflow before the fix and confirms an oversized page now resolves safely. The full local suite passes 81 tests; compilation, dependency consistency, and dependency audit pass.
- Windows 11 standalone package rebuilt from the combined source: ZIP SHA-256 `0AA5E9500066ACCB7D5FF86C117DCD1C23A9A8D20EF78DB6C30335C73465EE4B`. `windows/Test-Package.ps1` passed: health true, development mode, branded login HTTP 200, and 67.3 MiB working set. Build output/work, test database, and logs were isolated under temporary directories; no provider credentials were used.
- GitHub CI for that earlier source revision is historical and is not evidence for the current branch tip.
## Personal WhatsApp assisted flow — 2026-10-13

- Confirmed the personal-account path is assisted-only: the operator pastes the relevant text, the app analyzes it locally and checks Google Calendar, and the operator manually sends the prepared private booking link from WhatsApp. The app does not read the personal inbox or send personal WhatsApp messages. Existing `tests/test_assisted_personal.py` and `tests/test_frontend.py` passed: 11 tests.
- Real Google OAuth/Calendar, personal WhatsApp use, public ngrok reachability, HAI runtime, and target-PC acceptance remain unverified.

## HAI json-feed contract correction — 2026-10-14

- Compared the live HAI `json-feed` adapter in [`018-HAI/backend/internal/source/service.go`](https://github.com/Robert-Velhorst/018-HAI/blob/main/backend/internal/source/service.go): it reads `nextCursor` from the feed envelope and sends the saved value on a later request as the `cursor` query parameter.
- Agenda Relay previously returned only `cursor`. HAI therefore did not persist the continuation cursor and could keep retrieving only the initial bounded snapshot, missing later request updates. The older integration note incorrectly said HAI never returned a cursor.
- The feed now emits `nextCursor` and preserves `cursor` as a compatibility alias. The local integration test starts with a snapshot, adds a new request, then verifies the subsequent cursor request returns it.
- The HAI regression now also verifies a two-item initial snapshot advances to the newest item: an unchanged continuation returns no duplicate records, and a later new request is returned incrementally. HAI integration tests: 5 passed; full local suite: 112 passed. Live HAI source creation/sync and historical backfill remain unverified.

## Current Windows 11 package and launcher verification — 2026-10-14

- Built the standalone x64 package locally on Windows 11 Pro (build 26300). ZIP SHA-256: `94AF076E7330E003E34544A2432C80DA29629AD02A368F163C1CDAEF930A9ACE`; archive size 32.23 MiB.
- `windows/Test-Package.ps1` passed against the built executable with an isolated temporary database and provider credentials absent: health true, development mode, branded login HTTP 200, and 66.0 MiB working set.
- The source launcher now validates exact executable/command identity before treating recorded PIDs as Agenda Relay, checks health, recovers a missing worker without launching a duplicate web server, and avoids stopping recycled/unrelated PIDs. Its shutdown path retains state if process exit cannot be confirmed.
- The ngrok launcher and stop path now apply the same ownership discipline: process identity must match the saved ngrok executable, assigned domain, config files, and loopback destination. Failure cleanup and stop leave a mismatched/recycled PID untouched, and runtime state is retained if shutdown cannot be confirmed. Both Windows PowerShell versions passed the identity self-check; no public tunnel was opened.
- The process-identity/recovery self-check passed under PowerShell 7 and Windows PowerShell 5.1; all `windows/*.ps1` files parsed under PowerShell 7. The full Python suite passed (112 tests), `compileall` passed, and `pip check` reported no broken requirements. These checks do not replace real Google OAuth, ngrok exposure, or HAI runtime acceptance.
- This checkout has no `.env`, so no Google OAuth or application provider credentials were used. The ngrok executable and agent configuration are present, but no tunnel was opened.
- Exact SHA `01b45886928844b9c92087abad5ca6bf5407d9f9` passed the push CI run `38478527287`, PR CI run `38478532204`, Windows package run `38478532233`, and both CodeQL analyses in run `38478527776`. This includes the new Windows launcher self-check in the package workflow. GitHub emitted a Node.js 20 action deprecation advisory; it did not fail the run.

## WhatsApp delivery-status webhook follow-up — 2026-10-14

Signed Cloud API status receipts are now stored idempotently, displayed on the corresponding request, and included in privacy export/deletion and retention purge. The local test evidence covers phone-number scoping, malformed callback rejection, duplicate/out-of-order receipt handling, and absence of recipient IDs/raw payload fields. No live Meta webhook was configured or exercised.

- Full local suite: `115 passed`; `compileall`, `pip check`, and `git diff --check` passed. Ruff is not installed in the local venv; hosted CI is still pending for this follow-up.
- Windows 11 standalone package rebuilt and smoke-tested: health `true`, development mode, branded login HTTP 200, working set 66.1 MiB. ZIP SHA-256: `365E3258E1E258550012B297936B7420810B2CF81CFC1AFA67350A34CBFEDF92`.
- Build used no application/Google/Meta credentials. No live webhook subscription, ngrok tunnel, Google OAuth, or HAI runtime was exercised.
