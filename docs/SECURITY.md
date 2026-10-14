# Security and privacy design

## Trust boundaries

- Internet -> WhatsApp webhook: Meta HMAC required; body limited to 1 MB; only text fields are accepted.
- Browser -> operator actions: password-hash login, HttpOnly SameSite session cookie, one-hour lifetime, CSRF on state changes.
- API client -> operator API: constant-time bearer-token comparison.
- Application -> Google/Meta: HTTPS provider endpoints through official client libraries/APIs.
- Meta webhook messages: valid app-secret HMAC plus exact match to the configured WhatsApp phone-number ID before message processing.
- Container image and Compose services default to production configuration checks; missing or short data-encryption keys are rejected. Length validation does not establish key entropy: use the setup-generated cryptographically random key (or an equivalently random secret-manager value). Existing encrypted data is tied to the exact key; use the offline `rotate-encryption-key` migration command to create a verified replacement bundle before changing active paths or key configuration.
- Unknown `APP_ENV` values are rejected unconditionally. Development and test launchers bind only to loopback; external binds require production configuration checks.
- Login and contact-deletion rate limits use `X-Forwarded-For` only when the immediate peer belongs to `TRUSTED_PROXY_NETWORKS` (loopback by default for the local ngrok agent). Configure only proxy networks that cannot be bypassed. HAI network authorization continues to use the direct peer address and never trusts forwarded headers.
- Public booking link: 256-bit random bearer token stored encrypted and indexed only by SHA-256 hash; configurable expiry and proposal state prevent stale or post-confirmation reuse.
- HAI metadata feed: direct client IP allowlist; forwarded headers never grant access, and loopback requests carrying `X-Forwarded-For` are denied so the local public tunnel cannot inherit loopback access.

## Sensitive storage

Conversation bodies, proposal text, private booking tokens, and Google OAuth token JSON use Fernet encryption derived from `DATA_ENCRYPTION_KEY`. Production refuses to start without the key. Contact identifiers, appointment timestamps, and audit metadata remain visible to SQLite and require encrypted host volumes and restrictive filesystem permissions.

Secrets are environment-owned. They are excluded from Git, Docker build context, backups produced by Git, and support bundles. To rotate the data-encryption key, stop all web and worker processes and use the offline `rotate-encryption-key` CLI command to create and verify a non-overwriting replacement bundle. The command requires the current `DATA_ENCRYPTION_KEY`, a new `NEW_DATA_ENCRYPTION_KEY` of at least 64 characters, and a new output directory; it leaves the current database and token file unchanged. Test the replacement bundle with the new key before updating `DATABASE_PATH`, `GOOGLE_TOKEN_FILE`, and `DATA_ENCRYPTION_KEY`. Keep the originals until the rotated installation passes `doctor` and a read-only application check. Do not pass secrets on the command line or commit them.

Provider-token rotation and recovery:

1. Pause automation.
2. Back up the database and OAuth token file to encrypted storage.
3. Rotate Meta/Google tokens at the provider.
4. Update the host secret manager and run `doctor`.
5. Resume after one signed webhook and one provider connection check.

## Web security

Responses include CSP, frame denial, MIME sniff prevention, no-referrer, restricted browser permissions, no-store, and production HSTS. Production requires HTTPS and strong non-default secrets. OAuth uses a session-bound random state.
- Login return URLs and post-action referrers are restricted to local paths or validated same-host URLs whose paths cannot be interpreted as protocol-relative redirects. External, backslash, and control-character redirect candidates fall back to the dashboard.
- Public booking responses map expected validation errors to fixed text and never reflect raw calendar/provider exceptions to bearer-link holders; provider exception details remain restricted to operator-side recovery records.

## Authorization and ownership

Every domain table carries `workspace_id`; store queries require it. The shipped product has one configured workspace and one operator role. Team RBAC/SSO is not implemented, so this build must not be marketed as multi-tenant SaaS.

## Abuse and reliability controls

- Unique inbound message ID per workspace.
- Unique request source, proposal/request, appointment/request, booking token hash, job dedupe key, and Google event ID.
- Atomic per-contact outbound WhatsApp reservations per hour, including concurrent requests.
- Atomic inbound per-sender and workspace-wide quotas, a per-callback message cap, and a text-length cap for the optional Business API webhook.
- Emergency pause prevents new automatic scheduling/provider actions while preserving signed inbound records. The worker continues stale-claim recovery, proposal expiry, and retention housekeeping before it skips normal job execution.
- A proposal is atomically claimed before provider delivery, so simultaneous send actions cannot call WhatsApp twice.
- Provider timeouts and process interruption during external actions become visible manual exceptions instead of blind retries.
- Expired booking proposals are rejected equally through the private link and WhatsApp reply path.

`DATA_RETENTION_DAYS` purges inbound message bodies, rate events, and delivery receipts. `SCHEDULING_RETENTION_DAYS` (default 90) removes aged cancelled/failed requests, expired proposals after expiry plus the retention period, old cancelled appointments, and booked appointments only after their scheduled end is older than the retention period. Linked requests, proposals, and appointment reminder jobs are deleted with eligible appointments. Future appointments and failed/in-flight/manual-required bookings remain for operator recovery. Cleanup and its audit entry commit atomically: if the audit write fails, the deletions roll back. This cleanup does not delete Google Calendar events, unrelated unresolved scheduling records, or general audit history; use contact export/deletion controls for contact-associated personal data.

## Privacy controls

- Contact JSON export: `GET /api/contacts/<id>/export`.
- Contact deletion: `DELETE /api/contacts/<id>` removes messages, requests, proposals, appointments, and queued jobs, then retains a minimal deletion audit event.
- Personal WhatsApp assisted mode analyzes operator-pasted text in-process and does not store it in the message table or transmit it to Meta/AI. The structured request and booking proposal are retained to provide the booking-link workflow; avoid pasting unrelated or sensitive chat content.
- Scheduled retention purges inbound message bodies, rate events, delivery receipts, aged terminal scheduling records, expired proposals, completed bookings, and old cancellations according to their separate retention settings; future/recovery appointments, Google Calendar events, and general audit history are preserved.
- Booking page requires explicit scheduling consent; contact consent can be revoked in the dashboard.

## Threat-model residual risks

- SQLite metadata is not field-encrypted; use full-volume encryption and host access controls.
- Private booking links can be used by anyone who receives the URL until the configured expiry or proposal closure; keep the default seven-day TTL short for sensitive workflows.
- SQLite-backed browser login throttling is atomic on one host but not globally distributed; place a rate-limiting reverse proxy in front of horizontally scaled public deployments.
- Proxy-aware login/deletion rate limiting assumes the configured proxy overwrites or appends a truthful client address in `X-Forwarded-For`; do not trust networks reachable directly by untrusted clients.
- No organization SSO, hardware-backed keys, DLP, SIEM export, or independently audited cryptography deployment exists.
- WhatsApp API acceptance does not prove delivery/read. Signed callbacks are retained as provider-reported events and shown in the UI. Stored receipt data is limited to provider message ID, status, timestamp, bounded error code, and local receipt time; recipient IDs and raw payloads are not stored. Receipts follow retention and contact export/deletion. Missing or delayed callbacks remain unknown and never trigger resend or booking transitions. Personal WhatsApp has no provider status channel.
- The personal flow is manual-only: the operator opens WhatsApp, chooses the recipient, sends the draft, then separately confirms sharing to activate the link. The app cannot verify that action. Personal-flow proposals, confirmations, and reminders are blocked from Business API delivery.
