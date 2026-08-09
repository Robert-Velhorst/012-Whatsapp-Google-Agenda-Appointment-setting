# Security and privacy design

## Trust boundaries

- Internet -> WhatsApp webhook: Meta HMAC required; body limited to 1 MB; only text fields are accepted.
- Browser -> operator actions: password-hash login, HttpOnly SameSite session cookie, one-hour lifetime, CSRF on state changes.
- API client -> operator API: constant-time bearer-token comparison.
- Application -> Google/Meta: HTTPS provider endpoints through official client libraries/APIs.
- Public booking link: 256-bit random bearer token stored encrypted and indexed only by SHA-256 hash; configurable expiry and proposal state prevent stale or post-confirmation reuse.

## Sensitive storage

Conversation bodies, proposal text, private booking tokens, and Google OAuth token JSON use Fernet encryption derived from `DATA_ENCRYPTION_KEY`. Production refuses to start without the key. Contact identifiers, appointment timestamps, and audit metadata remain visible to SQLite and require encrypted host volumes and restrictive filesystem permissions.

Secrets are environment-owned. They are excluded from Git, Docker build context, backups produced by Git, and support bundles. Rotation procedure:

1. Pause automation.
2. Back up the database and OAuth token file to encrypted storage.
3. Rotate Meta/Google tokens at the provider.
4. Re-encrypt data with an offline migration before changing `DATA_ENCRYPTION_KEY`; changing the key without migration makes existing ciphertext unreadable.
5. Update the host secret manager and run `doctor`.
6. Resume after one signed webhook and one provider connection check.

## Web security

Responses include CSP, frame denial, MIME sniff prevention, no-referrer, restricted browser permissions, no-store, and production HSTS. Production requires HTTPS and strong non-default secrets. OAuth uses a session-bound random state.

## Authorization and ownership

Every domain table carries `workspace_id`; store queries require it. The shipped product has one configured workspace and one operator role. Team RBAC/SSO is not implemented, so this build must not be marketed as multi-tenant SaaS.

## Abuse and reliability controls

- Unique inbound message ID per workspace.
- Unique request source, proposal/request, appointment/request, booking token hash, job dedupe key, and Google event ID.
- Atomic per-contact outbound WhatsApp reservations per hour, including concurrent requests.
- Emergency pause blocks outbound messages, calendar changes, and workers while preserving signed inbound records.
- A proposal is atomically claimed before provider delivery, so simultaneous send actions cannot call WhatsApp twice.
- Provider timeouts and process interruption during external actions become visible manual exceptions instead of blind retries.
- Expired booking proposals are rejected equally through the private link and WhatsApp reply path.

## Privacy controls

- Contact JSON export: `GET /api/contacts/<id>/export`.
- Contact deletion: `DELETE /api/contacts/<id>` removes messages, requests, proposals, appointments, and queued jobs, then retains a minimal deletion audit event.
- Scheduled retention purge removes expired message bodies and rate events.
- Booking page requires explicit scheduling consent; contact consent can be revoked in the dashboard.

## Threat-model residual risks

- SQLite metadata is not field-encrypted; use full-volume encryption and host access controls.
- Private booking links can be used by anyone who receives the URL until the configured expiry or proposal closure; keep the default seven-day TTL short for sensitive workflows.
- SQLite-backed browser login throttling is atomic on one host but not globally distributed; place a rate-limiting reverse proxy in front of horizontally scaled public deployments.
- No organization SSO, hardware-backed keys, DLP, SIEM export, or independently audited cryptography deployment exists.
- Provider delivery acceptance does not prove WhatsApp delivery/read status; current UI reports only API acceptance.
