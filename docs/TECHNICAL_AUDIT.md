# Technical audit

Date: 2026-08-08

## Starting point

The linked GitHub repository had no default branch or usable files. The supplied archive contained multiple competing flat Python/React implementations whose imports expected a missing `src/` structure. A small standalone Flask MVP was subsequently created in this directory. It had verified inbound signatures, message deduplication, deterministic intent detection, Google FreeBusy lookup, pending suggestions, and four tests, but it did not complete the requested booking path.

There was no Git repository in this deliverable directory. This run initialized `main` and set the supplied GitHub URL as `origin`. Starting commit: none (unborn branch).

## Preserved working behavior

- Official WhatsApp Cloud API webhook verification and HMAC validation.
- Sender-specific recent-message context and idempotent inbound handling.
- Deterministic English/Dutch scheduling-intent detection.
- Google Calendar FreeBusy availability calculation in `Europe/Amsterdam`.
- Approval-first outbound proposals and explicit auto-send opt-in.

## Material gaps found

- No contact confirmation state, appointment record, or Google event write.
- No reminder worker, approved-template boundary, cancellation, or recovery workflow.
- No browser operator interface, session authentication, CSRF protection, or UI action audit.
- No workspace ownership columns, encrypted sensitive fields, privacy export/delete, retention, or audit history.
- No configuration fail-closed production mode, migration ledger, backup/restore, doctor command, Docker build, or CI.
- No comprehensive acceptance, security, operator, API usage, or completion evidence.

## Implemented architecture

The application remains a deliberately small Flask/SQLite system with server-rendered HTML. It now has four separable layers:

1. Provider adapters: signed WhatsApp Cloud API and Google Calendar FreeBusy/Events.
2. Domain service: message interpretation, proposal, confirmation, booking, cancellation, and reminder orchestration.
3. Persistence: forward-only migrations, workspace-scoped records, encryption for conversation bodies/tokens, state transitions, idempotency keys, jobs, rate events, and audit events.
4. Operator/public UI: authenticated exception desk and private contact booking page.

SQLite is suitable for one small operator deployment. A horizontally scaled SaaS deployment would require PostgreSQL, distributed rate limiting/job claims, organization identity, and per-workspace provider credentials.

## Dependency and file audit

- Runtime: Python 3.11-3.13, Flask, Waitress, Google API clients, Requests, Cryptography.
- Test: pytest with provider fakes kept under `tests/` only.
- Direct dependencies are declared in `requirements.txt`; the verified environment is pinned in `requirements.lock`.
- Runtime paths (`.env`, `data/`, SQLite files, logs, backups, support bundles, caches, credentials) are git-ignored and Docker-ignored.
- There are no upload or media endpoints; file/path-traversal phases are not applicable to the shipped surface.

## Honest production verdict

The repository now contains deployable application code and a verified local critical path. It is not confirmed production-ready because real Meta/Google credentials, public HTTPS routing, platform approvals, provider quotas, and a real operator rehearsal remain outside this workspace.
