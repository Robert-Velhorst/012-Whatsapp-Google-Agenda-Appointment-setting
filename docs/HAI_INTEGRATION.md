# HAI integration

Agenda Relay exposes a read-only JSON feed that the current HAI `generic_json_feed` parser can ingest as a bounded snapshot. The feed is disabled by default and contains scheduling metadata only: no phone number, email address, contact name, WhatsApp body, booking token, provider token, or Google event URL. This is not yet a reliable incremental-sync integration: the current HAI HTTP feed path performs a plain GET and does not persist or send the returned cursor on the next request.

## Agenda Relay configuration

```dotenv
HAI_CONNECTOR_ENABLED=true
HAI_ALLOWED_NETWORKS=127.0.0.1/32,::1/128
HAI_FEED_PAGE_SIZE=100
HAI_PROJECT_KEY=012-Whatsapp-Google-Agenda-Appointment-setting
```

The endpoint is `GET /api/integrations/hai/feed`. Agenda Relay returns `{ "items": [...], "cursor": "...", "nextCursor": "..." }`. The current HAI parser recognizes `cursor`; `nextCursor` is an Agenda Relay compatibility field and should not be assumed to be consumed by HAI. Each item includes `externalId`, `title`, `content`, `itemType`, `provider`, `receivedAt`, and `metadata`; metadata is a JSON object, not an encoded JSON string. The item type is HAI's supported `message` type and the provider is HAI's `generic_json_feed` provider identifier. Items declare `authority=advisory_read_only`; the connector cannot send WhatsApp messages or modify Google Calendar. Cursor continuations use the parent request's `updated_at`; projected request, proposal-status, and appointment-status mutations advance that timestamp in the same database transaction, including send recovery and failed Calendar reconciliation states.

The current HAI HTTP reader requests the configured URL as-is; it does not add `?cursor=` between syncs, even though HAI parses the `cursor` field into its sync report. Therefore repeated HAI syncs request the same bounded snapshot of the most recently updated records (100 by default, configurable up to 500). Stable `externalId` values allow HAI to deduplicate repeated items, but records that fall outside the snapshot can be missed if enough newer requests arrive between syncs. Do not treat this as incremental synchronization or complete historical backfill. Reliable cursor advancement requires a corresponding HAI reader/registry change and an end-to-end acceptance test.

## HAI connected source

For a same-host HAI deployment, create an owner-scoped HAI source with:

- connector: `json-feed`
- sync target: `http://127.0.0.1:5000/api/integrations/hai/feed` when HAI runs on the host
- local only: `true`
- permissions: `metadata`, `read`
- project: the configured `HAI_PROJECT_KEY`

HAI's current HTTP feed implementation disables HTTP feeds unless its policy opt-in is enabled. Its safe fetcher permits loopback only for an explicitly configured exact URL; use that mechanism for a same-host `127.0.0.1` endpoint. Verify the HAI deployment's HTTP-feed policy and exact loopback URL setting before syncing.

The previous Docker Desktop recipe using `host.docker.internal` is not supported by the current HAI safe fetcher: its resolved private IP is rejected. Adding that name to a connected-source host allowlist does not bypass the fetcher's private-network check. Do not broaden either product's network allowlist to work around this.

## Hetzner deployment

Hetzner replaces the former local-tunnel deployment path; ngrok is not required. Caddy on the Hetzner host provides public HTTPS for the booking experience and configured provider callbacks. Keep the HAI feed off that public path. The supported design to validate first is HAI running as a host process on the same Hetzner server and reading Agenda Relay through the loopback URL above. This keeps the feed on the machine and does not require a tunnel or a public feed endpoint.

Agenda Relay itself runs in Docker and publishes port 5000 only on host loopback. Before enabling HAI on a Linux host, verify the actual peer address that reaches the container through Docker's loopback-published port. If it is not loopback, add only the observed, exact peer address as a `/32` (or `/128`) in `HAI_ALLOWED_NETWORKS`; do not guess a Docker subnet or allow a broad private range. Confirm that the HAI exact-loopback URL policy and HTTP-feed opt-in permit the intended `http://127.0.0.1:5000/api/integrations/hai/feed` URL, then test a successful sync and a denied request from outside the host. Do not expose port 5000 directly.

HAI running in another container or on a different server is not a supported deployment yet. Container loopback is container-local, and the current HAI safe fetcher rejects private-network destinations. A private-network connector path would need a narrowly scoped HAI fetch policy, explicit Agenda Relay authentication or equivalent isolation, and end-to-end network/security tests before it should be enabled. Do not publish the feed through Caddy or widen either application's network allowlist as a workaround.

## Network boundary

Agenda Relay evaluates only the direct client address. It does not trust `X-Forwarded-For` for access control. If a loopback request includes that header, the feed denies it, which keeps requests arriving through a public reverse proxy from inheriting loopback access. Requests outside `HAI_ALLOWED_NETWORKS` fail with 403; disabled feeds return 404. The feed is bounded to 500 records per request and 60 requests per minute per direct peer.

For a same-host setup, keep HAI and Agenda Relay loopback-only. Do not add the HAI feed URL to an externally accessible source or allowlist a public network. HAI remains responsible for owner/workspace authorization and its own source retention policy. The current feed contract is cursor-capable and bounded; the checked-in HAI HTTP reader still does not persist and resend the cursor. A separate, uncommitted HAI cursor-continuation patch exists locally but is not present in the checked-in HAI revision. Therefore live HAI sync, cross-container connectivity, cursor persistence in the published HAI code, loss-free pagination, and complete historical backfill remain unverified or unsupported. The same-host Hetzner network path also requires Linux/Docker acceptance before production use.
