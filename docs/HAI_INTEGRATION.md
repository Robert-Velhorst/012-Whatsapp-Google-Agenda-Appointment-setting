# HAI integration

Agenda Relay exposes a read-only, cursor-based feed compatible with HAI's operational `json-feed` connected-source adapter. The feed is disabled by default and contains scheduling metadata only: no phone number, email address, contact name, WhatsApp body, booking token, provider token, or Google event URL.

## Agenda Relay configuration

```dotenv
HAI_CONNECTOR_ENABLED=true
HAI_ALLOWED_NETWORKS=127.0.0.1/32,::1/128
HAI_FEED_PAGE_SIZE=100
HAI_PROJECT_KEY=012-Whatsapp-Google-Agenda-Appointment-setting
```

The endpoint is `GET /api/integrations/hai/feed`. Its envelope is `{ "items": [...], "nextCursor": "..." }`, matching HAI's existing `json-feed` contract. HAI appends the returned cursor on the next incremental sync. Items declare `authority=advisory_read_only`; the connector cannot send WhatsApp messages or modify Google Calendar.

## HAI connected source

Create an owner-scoped HAI source with:

- connector: `json-feed`
- sync target: `http://127.0.0.1:5000/api/integrations/hai/feed` when HAI runs on the host
- local only: `true`
- permissions: `metadata`, `read`
- project: the configured `HAI_PROJECT_KEY`

When HAI runs in Docker Desktop, use `http://host.docker.internal:5000/api/integrations/hai/feed`, add `host.docker.internal` to HAI's `CONNECTED_SOURCE_HTTP_ALLOWED_HOSTS`, and add only the observed Docker gateway address/CIDR to `HAI_ALLOWED_NETWORKS`. Do not use a broad private-network CIDR without checking the actual source address.

## Network boundary

Agenda Relay evaluates the direct client address. When the direct peer is loopback, it also evaluates the first `X-Forwarded-For` address so an external ngrok request cannot inherit loopback trust. Requests outside `HAI_ALLOWED_NETWORKS` fail with 403; disabled feeds return 404. The feed is bounded to 500 records per request and 60 requests per minute per direct peer.

For a same-host setup, keep HAI and Agenda Relay loopback-only. Do not add the HAI feed URL to an externally accessible source or allowlist a public network. HAI remains responsible for owner/workspace authorization and its own source retention policy.
