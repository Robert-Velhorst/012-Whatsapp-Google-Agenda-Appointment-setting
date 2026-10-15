# Giant prompt completion matrix

Status is evidence-based as of 2026-10-15. `Implemented` means locally wired and tested. `Partial` identifies a real remaining gap. `Blocked` is reserved for provider/account/deployment action unavailable in this workspace.

| Phase | Requirement | Status | Evidence / gap |
|---:|---|---|---|
| 000 | Repository integrity | Implemented | Technical audit, Git initialization, runtime ignores |
| 001 | File/dependency audit | Implemented | Audit, exact direct and environment lock files |
| 002 | Product outcome contract | Partial | Single-workspace ownership enforced; multi-tenant product not shipped |
| 003 | Critical path smoke test | Implemented | Critical-path test and document |
| 004 | Architecture validation | Implemented | Fail-closed production and labelled modes |
| 005 | Data model/persistence | Implemented | Migrated domain tables, FKs, indexes, state transitions |
| 006 | Configuration guards | Implemented | `Settings.validation`, production startup refusal |
| 007 | Authentication/session | Implemented | Password-hash session and bearer API, CSRF on operator and public booking forms |
| 008 | Authorization/ownership | Partial | Workspace-scoped single operator; no team RBAC/SSO |
| 009 | API/error envelope | Implemented | Protected JSON endpoints and structured errors |
| 010 | Frontend/navigation | Implemented | Server-rendered accessible application shell |
| 011 | Core vertical slice | Implemented | Webhook through event/reminder/audit |
| 012 | Provider reality review | Partial | Official adapters wired; signed WhatsApp status callbacks are retained and displayed; cancellation/reschedule appointment-state changes advance the parent request cursor; real credentials/acceptance remain unavailable. Checked-in HAI `main` at `345cf356c3f4ab497568713dc994820b4ba22b10` parses `cursor` but uses a plain GET. The separate uncommitted HAI working-tree patch sends/persists the cursor and passes `go test ./...`, `go vet ./...`, ten repeated cursor-checkpoint tests, and the tagged registry migration/reconstruction test against an isolated disposable PostgreSQL 16 database. It remains unpublished and has not been accepted against a live HAI endpoint or Hetzner network path. |
| 013 | Compliance boundaries | Implemented | Official APIs only; reminder-template/manual boundary |
| 014 | No fake production success | Implemented | Fakes confined to tests; truthful provider states |
| 015 | Upload/media safety | Not applicable | Product exposes no upload/media routes |
| 016 | Jobs/workers | Implemented | Claimed reminder jobs, terminal/manual states, retention, stale-claim recovery, and serialized reminder claims against reschedule preparation/discard and cancellation |
| 017 | Idempotency | Implemented | Unique inbound/domain/job/event keys and atomic claims |
| 018 | Rate/provider quotas | Implemented | Atomic per-contact hourly outbound reservations; provider errors surfaced |
| 019 | Audit history | Implemented | Workspace-scoped audit events and UI/API |
| 020 | Dashboard/next action | Implemented | Exception queue and contextual actions |
| 021 | Forms/validation/autosave | Partial | Forms validate and save; autosave intentionally absent |
| 022 | Search/filter/pagination | Implemented | Workspace SQL filters and bounded pagination |
| 023 | Import/export | Partial | CSV and privacy JSON export; no data import |
| 024 | Templates/presets/defaults | Partial | Environment defaults and Meta template setting; no preset UI |
| 025 | AI abstraction/fallback | Implemented | `IntentProvider` with deterministic local default; English and Dutch relative/weekday date parsing |
| 026 | Review/approval gates | Implemented | Separate proposal and booking approvals by default |
| 027 | Notifications/reminders | Partial | Worker complete; real approved template not available |
| 028 | Privacy/delete | Implemented | Export, retention purge, consent controls, guarded API deletion, and CSRF-protected browser deletion requiring current-password reauthentication; active appointments must be cancelled first |
| 029 | Web security | Implemented | CSP, HSTS production, no-store, anti-frame/sniff/referrer |
| 030 | Secret management/rotation | Partial | Environment/secret mounts and a tested offline key-rotation bundle are available; no external vault integration or managed key rotation |
| 031 | One-command local development | Implemented | README/Makefile/locked environment commands |
| 032 | Docker/deployment | Partial | Hardened non-root image and Windows executable verified; Hetzner guide now documents the supported cloud path; no authorized live provider deployment |
| 033 | Migrations/rollback safety | Implemented | Forward ledger, backup/restore, pre-restore copy |
| 034 | CLI/doctor | Implemented | Migrate, doctor, worker, backup, restore, bundle, hash commands |
| 035 | Health/readiness | Implemented | Public minimal and protected detailed scheduling/ingress readiness |
| 036 | Operator diagnostics | Implemented | Settings readiness, audit, doctor, redacted support bundle |
| 037 | Demo mode labelling | Implemented | Development/test mode visibly labelled and guarded |
| 038 | Fake provider lab | Implemented | Test-only fake Calendar/WhatsApp fixtures |
| 039 | Test factories/fixtures | Implemented | Reusable signed webhook/provider fixtures |
| 040 | Backend tests | Implemented | Webhook, state, API, auth, privacy tests |
| 041 | Frontend/component tests | Partial | Server-render integration/browser QA; no JS component framework |
| 042 | Worker tests | Implemented | Unknown/missing reminder outcomes tested |
| 043 | End-to-end tests | Implemented | Full local critical path with provider boundaries |
| 044 | Acceptance matrix | Implemented | `docs/ACCEPTANCE_TESTS.md` |
| 045 | Adversarial tests | Partial | Signature, size, auth, CSRF, redirect, CSV, concurrency, state/retry tests; no external pentest |
| 046 | Cross-user isolation | Partial | Workspace isolation tested; multiple interactive users absent |
| 047 | File/path traversal tests | Not applicable | No user-selected file paths or uploads |
| 048 | Provider failure simulation | Implemented | Verified rejection versus ambiguous delivery states; malformed, timezone-free, zero-length, or reversed Calendar busy intervals fail closed before proposing or booking; ambiguous retries prohibited |
| 049 | Accessibility | Partial | Semantic labels/responsive/reduced motion; primary-navigation keyboard focus has a 2px blue outline (5.34:1 against focus background); mobile navigation reflows and the Settings metadata grid shrinks on narrow screens. Browser AX checks found no unnamed interactive controls across seven views; full WCAG audit remains pending |
| 050 | Responsive/browser compatibility | Implemented | Desktop and mobile browser QA passed with zero console warnings/errors |
| 051 | Performance/indexing | Implemented | WAL/persistent connections/indexes, bounded 1,000/10,000-record benchmarks, and one-transaction contact/request/audit writes; throughput remains host-variable |
| 052 | Large dataset/pagination | Implemented | 1,000-record dashboard/feed benchmark and bounded pagination verified |
| 053 | Backup/restore | Implemented | SQLite online backup, integrity check, pre-restore safety copy; default destination follows `DATABASE_PATH` into the persistent Docker data mount; encrypted off-host scheduling remains operator-configured |
| 054 | Reconciliation/repair | Partial | Integrity/doctor/retention supplied; advanced repair commands absent |
| 055 | Local-first analytics | Partial | Workload counts/audit local; no analytics event dashboard |
| 056 | SaaS readiness | Partial | Workspace fields present; billing intentionally absent; SaaS auth absent |
| 057 | EN/NL readiness | Partial | Intent/replies bilingual; operator UI is English |
| 058 | Feature flags | Implemented | Approval/auto-send/auto-book/pause flags and status |
| 059 | Formal state machines | Implemented | Explicit request transitions and terminal job/proposal states |
| 060 | Domain specification | Implemented | Critical path and architecture documents/code |
| 061 | Invariants/constraints | Implemented | Uniqueness/FKs/bounds/state validation |
| 062 | Pre-action review | Implemented | Detail rail shows context, slots, consent, timezone, audit |
| 063 | Credential checklist | Implemented | Doctor/readiness and operator/provider onboarding docs |
| 064 | Threat model | Implemented | Security trust boundaries and residual risks |
| 065 | Privacy impact | Implemented | Data inventory, consent, encryption, deletion, retention |
| 066 | Supply chain | Implemented | Locked environments, CI `pip-audit`, and live audit with no known vulnerabilities |
| 067 | License/third-party review | Partial | Providers/dependencies recorded; formal counsel review external |
| 068 | CI/CD gates | Implemented | Compile, tests, secret-safe Docker Compose configuration validation, and Docker build GitHub workflow |
| 069 | Release/canary/rollback | Partial | Procedure documented; no live deployment to exercise |
| 070 | Operator runbook | Implemented | Runbook covers daily, incidents, backup, release |
| 071 | User guide/help | Implemented | README plus in-app workflow help |
| 072 | Troubleshooting/error catalog | Implemented | `docs/TROUBLESHOOTING.md` |
| 073 | UI action audit | Implemented | Every visible action mapped to route/effect/failure |
| 074 | API usage audit | Implemented | Public/operator/provider surfaces mapped |
| 075 | Documentation truthfulness | Implemented | Partial/blocked status stated throughout |
| 076 | Debt register | Implemented | `docs/MAINTENANCE.md` |
| 077 | Bug hunt log | Implemented | Worklog records template, security, provider ambiguity, concurrency (including reminder/cancel/reschedule races), timezone, corrupt-restore, and contact-language/transaction fixes |
| 078 | Red-team loop one | Partial | Automated auth/signature/CSRF/size/state review; independent review absent |
| 079 | Red-team loop two | Partial | Privacy/isolation/encryption review; independent review absent |
| 080 | Red-team loop three | Partial | Provider ambiguity/idempotency review; real-provider chaos test blocked |
| 081 | Non-technical simulation | Partial | Help/next-action UI implemented; real operator rehearsal pending |
| 082 | Autonomy-first review | Implemented | Automatic analysis/slots with exception-only approvals |
| 083 | Value review | Implemented | Removes availability checking/data-entry loop |
| 084 | Product realism | Partial | Local workflow real; provider proof blocked |
| 085 | Traceability | Implemented | This phase-by-phase matrix |
| 086 | Task graph | Implemented | `docs/TASK_GRAPH.md` |
| 087 | Worklog/checkpoints | Implemented | Both required documents present |
| 088 | Context-loss resume | Implemented | Checkpoints name exact remaining gates |
| 089 | Stabilization gates | Implemented | Config -> tests -> UI -> Docker -> real-provider sequence |
| 090 | No vanity work | Implemented | Dominant work is wired critical path/operations |
| 091 | Feature definition of done | Implemented | Implemented status requires wired/tested/documented behavior |
| 092 | Fresh-clone dry run | Implemented | Remote branch and package workflow verified; final 37-test CI evidence recorded in final report |
| 093 | Manual verification evidence | Implemented | Desktop/mobile browser, Docker, source launcher, packaged executable, backup/restore evidence |
| 094 | Final no-excuses search | Implemented | Secret signatures, TODO markers, encoding, ignores, and action truth scanned before publication |
| 095 | Completion matrix | Implemented | This document |
| 096 | Final verification report | Implemented | `docs/FINAL_VERIFICATION_REPORT.md` records commands, results, checksum, and external gate |
| 097 | Final response requirements | Implemented | Final handoff reports outcome, evidence, artifacts, PR, and external gates |
| 098 | Maintenance plan | Implemented | `docs/MAINTENANCE.md` |
| 099 | Roadmap/blocked items | Implemented | Maintenance roadmap and explicit external gates |
| 100 | Real-provider cleanup/account safety | Blocked | Requires authorized Meta/Google accounts and test data cleanup |
| 101 | Support bundle | Implemented | Redacted CLI bundle excludes PII/secrets |
| 102 | Retention/archive policy | Implemented | 90-day purge of old resolved/cancelled appointments and expired records; retains future/recovery work, Google Calendar events, and audit history |
| 103 | Prototype-to-production | Partial | Guards/Docker/ops complete; real deployment/security validation blocked |

| 104 | Emergency controls | Implemented | Persistent pause and inbound record-only behavior; resume is blocked until required integrations are ready |
| 105 | First-run onboarding | Partial | Login/readiness/help guide; no multi-step credential wizard |
| 106 | Roles/team permissions | Partial | Single operator only; no teams/RBAC |
| 107 | Quality/confidence | Implemented | Deterministic confidence stored and displayed |
| 108 | Human decision minimization | Implemented | Only proposal/booking exceptions gated; opt-in automation flags |
| 109 | Exception dashboard | Implemented | Queue organized by next action and provider attention |
| 110 | Safe retry/recovery | Implemented | Atomic claims, stale-work recovery, and ambiguous sends become manual |
| 111 | Ambiguous external action | Implemented | Calendar ID recovery; WhatsApp timeout is not blindly retried |
| 112 | Version/changelog | Implemented | Versioned health/package and `CHANGELOG.md` |
| 113 | Regression baseline | Implemented | Automated suite covers critical invariants |
| 114 | Maintenance/refactoring | Implemented | Layered modules and debt register replace flat prototype |
| 115 | Human-operator readiness | Partial | Usable dashboard/runbook; authorized real-provider rehearsal blocked |

## Personal WhatsApp assisted-flow update (2026-10-13)

The operator can paste a relevant message into the authenticated **Personal WhatsApp** screen. Local English/Dutch rules detect a scheduling request, Google FreeBusy returns candidate times, and the app prepares a private booking link and a WhatsApp draft. The pasted text is not persisted or sent to an AI or WhatsApp API. The operator manually opens WhatsApp, chooses the recipient, sends the message, and confirms sharing before the booking link becomes active. The recipient selects a time and grants consent; Calendar booking follows the configured approval setting. Personal confirmations and reminders remain manual, and Personal-flow records are blocked from Business API sending. Regression coverage is in `tests/test_assisted_personal.py` and `tests/test_security_privacy.py`.

`WHATSAPP_CLOUD_API_ENABLED=false` supports a production personal-only setup without Meta credentials; Google OAuth, strong secrets, HTTPS `PUBLIC_BASE_URL`, and a reachable public booking link are still required. No live WhatsApp inbox, Hetzner deployment, Google account, or calendar was connected or exercised by this change. Full CI and hosted/provider acceptance are separate gates.

## Targeted follow-up — 2026-10-14

- Added an operator reconciliation action for stale Calendar bookings. It performs a read-only lookup of the deterministic event, validates active status, Agenda Relay appointment marker, and exact timezone-aware start/end values, then atomically restores the appointment/request to booked. If no event exists, it exposes a separate explicit retry. Provider errors or event mismatches leave the manual-review state intact. No WhatsApp confirmation is sent during recovery; personal-flow confirmations remain operator-assisted. Commit `a4aef7c` passed 141 local tests plus exact-commit GitHub CI and Windows package workflows; the additional responsive CSS regression fix below has since passed 142 local tests and awaits fresh hosted checks.
- App-wide responsive QA found that the selected-request detail rail was hidden below 1180px, making the confirmation draft and booking controls inaccessible on tablet/mobile despite a selected request. It now appears below the queue at narrower widths. A synthetic browser walkthrough verified assisted analysis, manual-sharing activation, consented slot choice, operator booking, and the personal confirmation draft at 390px; page width remains 390px with no horizontal page overflow. Added a static regression guard; the current 142-test source passed GitHub's Windows package workflow (run `38494863561`) and an isolated local Windows 11 executable/package smoke test. General CI run `38494863543` remains queued.

- Calendar retry safety: migrations 7–8 persist the booking attempt and backfill legacy in-flight/failed appointments to attempt 1, preserving their existing deterministic event ID. A separately claimed retry increments the counter and uses a new deterministic ID, preventing a tombstoned 409 ID from making the advertised retry unusable. Targeted regressions: 27 passed; full suite: 145 passed; compileall, pip check, and diff check passed. Exact-head hosted checks remain pending.

- Personal confirmation audit correctness: intentional manual follow-up after an assisted booking is now recorded as `confirmation.manual_required` rather than a failed send. Tests assert the personal flow never invokes the automatic sender, while Business API send failures retain their existing handling. Full local suite: 145 passed.

- SQLite close contention: exact-head Linux CI had a real failure under 24-way rate-limit reservation because every thread ran `PRAGMA optimize` as it closed its connection. Removed that unnecessary per-thread write-capable shutdown step; the concurrency regression and full 145-test suite pass locally, along with compileall, pip check, and diff check. Fresh exact-head hosted checks are pending.

- Request/audit atomicity and write efficiency: an injected audit failure reproduced a request row committed without its audit entry. `Store.create_request` now writes both rows in one transaction; a profiled 500-record/two-pass synthetic workload uses 2,222 commits instead of 3,222 (31% fewer). Three-run throughput medians were 164.4/s before and 684.0/s after, but remain host-variable and are not a capacity guarantee. The injected-failure regression and full local suite (171 passed) passed. Exact pushed head `9f4eaf6f063907d8e47bad2058ae56d9981e0ee9` also passed hosted Analyze, both Verify jobs, CodeQL, and the Windows package workflow; run IDs and the live-provider distinction are recorded in `docs/CODEX_WORKLOG.md`.

- Assisted confirmation-field accessibility: local browser QA found the readonly personal confirmation textarea lacked a stable `id` and `name`. Added a stable identifier and heading-based accessible name with a regression assertion. Post-fix browser inspection confirmed the identifiers and accessible name, no console errors/warnings, and no horizontal overflow at 2,560 pixels. A screenshot and mobile viewport check remain outstanding.

- Historical Windows tunnel work closed an OAuth bootstrap deadlock using the protected `public_ingress` readiness contract. The tunnel launcher has since been removed because production ingress is now Hetzner; the live deployment procedure is documented in `docs/HETZNER_DEPLOYMENT.md`.
- Closed an unsafe resume path: the operator action cannot resume automation while configuration errors or provider disconnections remain.
- Historical regression evidence: `tests/test_hai_integration.py` covers paused/unpaused OAuth bootstrap and authenticated readiness; `tests/test_security_privacy.py` covers the refused resume and visible error message. Full suite: 66 passed; dependency audit and consistency checks passed; the PowerShell parser accepted the then-existing `windows/Start-Ngrok.ps1`, which has since been removed.
- No Hetzner deployment or live provider action was run. DNS/TLS exposure, Google consent, any selected Meta callback, and the end-to-end provider acceptance matrix remain external gates.
- The HAI feed's item/provider/metadata shape and cursor behavior were checked against the current [`018-HAI` parser](https://github.com/Robert-Velhorst/018-HAI/blob/12246bd28820f892a48e04b528ff8e28b102b7d4/backend/internal/accountfeed/generic_feed.go), [`HTTP fetcher`](https://github.com/Robert-Velhorst/018-HAI/blob/12246bd28820f892a48e04b528ff8e28b102b7d4/backend/internal/accountfeed/fetcher.go), and [`registry service`](https://github.com/Robert-Velhorst/018-HAI/blob/12246bd28820f892a48e04b528ff8e28b102b7d4/backend/internal/accountfeed/registry_service.go) at `12246bd28820f892a48e04b528ff8e28b102b7d4`. The parser recognizes `cursor` but not `nextCursor`; the fetcher issues a plain GET, and the registry does not persist/send the cursor on later reads. Accordingly, HAI currently receives a bounded latest-record snapshot, not incremental synchronization. Local Agenda Relay cursor tests do not prove that HAI sends continuation requests. The separate HAI patch remains local; live HAI ingestion and reliable pagination remain unverified.
- Rechecked the live `018-HAI` `main` at [`b7e3ad2086c23313a0355101498bee82cda62d4e`](https://github.com/Robert-Velhorst/018-HAI/commit/b7e3ad2086c23313a0355101498bee82cda62d4e). Its parser/fetcher/registry still parse a returned cursor but neither send nor persist it for the next request. The cursor-continuation patch remains uncommitted and local-only. Its focused `go test ./internal/accountfeed ./migrations` and `go vet ./internal/accountfeed` pass using an isolated Go 1.27.2 toolchain. The tagged PostgreSQL integration test was not run: its dedicated test DSN is unset, `psql` is unavailable, and the Docker server did not respond. Agenda Relay must therefore continue to describe live HAI as bounded-snapshot-only.
- Windows 11 package key-rotation smoke: updated `windows/Test-Package.ps1` to seed three synthetic encrypted values and require all three to rotate, then built and smoke-tested the standalone ZIP locally. SHA-256 and exact test outcome are recorded in `docs/FINAL_VERIFICATION_REPORT.md`; provider credentials and live provider acceptance were not involved.
- Added a narrow, authenticated reconciliation action for ambiguous Business API proposal delivery. It records an operator's provider-verified outcome atomically with an audit event; verified delivery advances to awaiting contact confirmation, and verified non-delivery only enables a separate explicit retry. It never calls WhatsApp and does not reconcile other ambiguous job types. Regression tests cover CSRF rejection, transitions, and no-send behavior.
- Fixed prefix-prone appointment ID matching in reminder cancellation and contact deletion. Both operations now parse candidate job payloads and compare the exact integer `appointment_id`; cancellation only changes pending reminder jobs, while privacy deletion removes all and only jobs belonging to the deleted contact's appointments in that workspace. Regression tests cover prefix IDs and workspace isolation.
- Hardened appointment/request transitions against cancellation during calendar booking and partial commits. Proposal creation/send/confirmation/expiry/reconciliation, booking claim/completion/failure/recovery, manual sharing, and cancellation now write coupled state and transition audit in one SQLite transaction; cancellation during `booking` returns HTTP 409. Regression injects an audit-write failure and proves rollback, and covers stale-booking recovery consistency.
- At the earlier reconciliation checkpoint, 102 tests passed; Ruff, compilation, and `git diff --check` passed. A local synthetic browser session verified the reconcile-delivered UI transition and audit entry. For commit `ec83cd0`, the Windows package workflow passed, including hosted tests and package smoke test. Live HAI and provider acceptance remain unverified.
- Historical Windows launcher follow-up: exact process identity, health-gated recovery, missing-worker recovery, and fail-closed stop behavior have PowerShell self-checks; they passed under PowerShell 7 and Windows PowerShell 5.1. The source package smoke and 112-test Python suite passed locally. Exact source SHA `01b45886928844b9c92087abad5ca6bf5407d9f9` passed push CI, PR CI, Windows package, and CodeQL; run IDs and remaining live-acceptance gates are recorded in `docs/FINAL_VERIFICATION_REPORT.md`. Later follow-ups extended HAI cursor and then-existing tunnel process-ownership coverage; verify current PR checks for the latest commit.

## Backup path follow-up (2026-10-14)

The CLI's default online backup now lands in a `backups` folder beside the configured database. With the default Compose configuration this is `/app/data/backups`, persisted through the host's `./data` mount; this is still only an on-host copy, so the documented encrypted off-host schedule and restore drills must be configured separately. The focused CLI tests and full local suite passed (242 tests). A current-source Windows 11 x64 package was built and its isolated smoke test verified migrations, three encrypted-field rotation, default backup creation, health, and branded login. This does not establish a live Hetzner deployment, off-host backup automation, or provider acceptance.

## Calendar operation recovery follow-up (2026-10-14)

Booked-event cancellation now uses a durable `cancelling` claim, atomic local completion, stale-operation recovery, and a read-only reconciliation path for ambiguous provider results. An operator-reviewed reschedule keeps the original booking authoritative while checking and reviewing a proposed timezone-aware interval; confirmation rechecks availability, patches only event times, verifies the resulting Google event, and then updates local state and queued reminders. Ambiguous or stale updates require read-only reconciliation. Parent request cursor timestamps are touched as appointment states change, allowing HAI clients to observe completed reschedules. Local evidence: 275 Python tests passed; `compileall`, `pip check`, and `git diff --check` passed; a current Windows 11 x64 package passed its isolated migration/encryption/backup/health/login smoke test. Ruff is unavailable in the local environment and hosted CI is pending for the pushed commit. Neither this work nor the earlier verification used a live Google account, WhatsApp conversation, or Hetzner host.

## OAuth and assisted-flow reliability follow-up (2026-10-14)

Google refresh-token failures now give safe reconnect/retry guidance, and readiness preserves that distinction instead of labelling a transient transport outage as missing OAuth. Personal assisted-mode Calendar failures no longer render or persist raw provider exception messages; audits retain only the provider and exception class. Local evidence: 281 Python tests passed; compilation, dependency check, and diff check passed. Exact-head commit `bb42458` passed hosted Windows packaging, dependency audits, tests, and package smoke. The newer readiness refinement requires a fresh exact-head CI run. No live Google account or Hetzner host was used.

## Date parsing correction — 2026-10-15

The personal-flow parser previously matched the `morgen` substring inside Dutch `overmorgen`, proposing tomorrow instead of the day after tomorrow; the English phrase “the day after tomorrow” also fell back to today. Exact-boundary parsing now distinguishes tomorrow from day after tomorrow, including Dutch day-part compounds. Regression tests reproduced both wrong outputs before the fix. The focused intent and assisted-flow suites passed (`42 passed`); the full local suite passed (`300 passed`), along with compilation, `pip check`, and `git diff --check`. Hosted exact-head checks for the follow-up commit are pending. No personal conversation or external provider was used.

## Overall verdict

The repository is a substantial, working single-operator implementation, not a disconnected mockup. The local critical path, desktop/mobile interface, Windows package, Docker runtime, schema-compatible HAI feed, security audit, and performance baseline are implemented and testable. It remains **Partial for live production operation** until an authorized Hetzner deployment and domain are provisioned and accepted, Google OAuth and real-provider behavior are verified, HAI runtime acceptance is completed, and the applicable acceptance matrix is passed. Meta Business API approval is only required if that optional mode is selected; personal-assisted mode remains manual-only.
