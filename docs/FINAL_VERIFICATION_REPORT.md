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
- The code and this verification addendum are pending push and GitHub CI verification.
