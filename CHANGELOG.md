# Changelog

## Unreleased

- Prevent duplicate Calendar events after ambiguous create/persistence failures by requiring reconciliation before retry; recover missing reminder jobs on idempotent booking retries.
- Serialize Google OAuth token refreshes across web/worker processes sharing the token file and atomically replace token contents.
- Make Hetzner the sole documented production ingress path, add a host/Caddy deployment and migration runbook, and remove obsolete ngrok launcher/configuration support.
- Publish support bundles atomically without overwriting an existing diagnostic archive.
- Resolve relative `.env`, SQLite, and Google credential/token paths from the executable folder in standalone builds, independent of shortcut working directory.
- Store signed WhatsApp Cloud API delivery-status callbacks idempotently and show the latest provider-reported status; receipts are included in contact export/deletion and retention.

## 1.0.0 - 2026-08-09

- Complete local critical path from signed WhatsApp message through reviewed proposal, contact confirmation, idempotent Google event, confirmation, reminder job, and audit trail.
- Add operator dashboard, public booking page, authentication/CSRF, production guards, encryption, ownership, privacy, retention, pause, rate limiting, migrations, CLI, Docker, CI, tests, and operational evidence.
- Add a verified Windows 11 executable/package, guarded temporary ngrok launcher (removed from the current deployment path), local read-only HAI feed, booking-link expiry, persistent SQLite/WAL performance improvements, package/runtime CI, and dependency auditing.
- Harden concurrent sends/confirmations and rate limits, ambiguous provider recovery, stale worker recovery, timezone display, CSRF, redirects, CSV export, and atomic OAuth token storage.

## 0.1.0 - 2026-07-25

- Initial approval-first webhook and Google FreeBusy MVP.
