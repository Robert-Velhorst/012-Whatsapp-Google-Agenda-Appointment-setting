# Hetzner production deployment

This is the supported production hosting path. It describes a single Hetzner Cloud Linux server running the existing Docker Compose web and worker services, with a host-managed Caddy reverse proxy providing public HTTPS. The app and SQLite database stay on the server; the app's published port remains loopback-only. This is a single-host deployment, not a highly available or horizontally scaled service.

This guide is a deployment plan, not evidence of a live deployment. No Hetzner server, DNS record, firewall, credential, or provider integration is changed by following repository tests.

## Topology and boundaries

```text
Internet ── HTTPS :443 / HTTP :80 ──> Caddy on Hetzner host
                                      │
                                      └── http://127.0.0.1:5000
                                           ├── Compose web container
                                           └── persistent ./data (SQLite + Google token)
Compose worker ── same persistent ./data ──> Google Calendar API (outbound HTTPS)
```

- Assign a stable public IPv4 address and a DNS hostname dedicated to Agenda Relay. Point its A record at the server; only publish an AAAA record if IPv6 is configured and reachable end to end.
- Apply both a Hetzner Cloud Firewall and a host firewall. Allow SSH only from administrator source addresses; allow inbound TCP 80/443 for public HTTP redirect, ACME/TLS, booking links, OAuth callback, and (only if enabled) Meta webhooks. Do not expose port 5000, SQLite, Docker, or Caddy's admin API.
- Caddy runs on the host and proxies to Compose's existing `127.0.0.1:5000` binding. Configure `TRUSTED_PROXY_NETWORKS` for the actual loopback peer only unless the topology demonstrably requires a narrower additional proxy address. Never trust arbitrary client-supplied forwarding headers.
- Compose currently uses a local SQLite file and shares `./data` between web and worker. Keep both services on one host and one durable, encrypted filesystem. Do not mount separate copies or run a second worker against a separate database. This product has not been validated for multiple app hosts.
- HAI feed remains disabled by default. Do not expose it through the public proxy. Current Docker-to-host HAI fetch limitations are documented in [HAI integration](HAI_INTEGRATION.md).

For the TLS and proxy pattern, see [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https) and [Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy). Hetzner Cloud Firewall rules are allowlists with implicit inbound deny; see [Hetzner firewall overview](https://docs.hetzner.com/cloud/firewalls/overview/). Follow the official [Docker Engine install guide](https://docs.docker.com/engine/install/) for the chosen server distribution.

## Before provisioning or cutover

Have an authorized operator decide and record:

1. Hetzner project, region, server size, OS image, IPv4/IPv6 policy, backup policy, and budget.
2. Domain/hostname and DNS owner. TLS issuance requires public DNS to resolve to this server and ports 80/443 to reach Caddy.
3. SSH key and administrator IP ranges; emergency console/recovery access.
4. Whether production is personal-assisted-only (`WHATSAPP_CLOUD_API_ENABLED=false`, recommended for the personal WhatsApp workflow) or the optional separately authorized WhatsApp Business Cloud API.
5. Which existing local database, encryption key, Google OAuth client and token, and provider settings are intended for migration. Never put real values in Git, chat, screenshots, or a support bundle.
6. Who owns restore testing, alert response, provider consent, and the public booking-link acceptance test.

Do not provision paid resources, change DNS/firewall, upload credentials, or import personal records without that operational authorization. For migration, preserve the existing installation until the cloud copy passes read-only checks and an explicit cutover is approved.

## Prepare the host

1. Create a supported Linux server in Hetzner Cloud and attach a restrictive Cloud Firewall before exposing it. Permit SSH only from trusted administrator addresses and TCP 80/443 as required. Keep outbound HTTPS and DNS available for operating-system updates, Docker image pulls, Google APIs, and (if enabled) Meta APIs.
2. Use SSH keys, disable password SSH after verifying key access, apply OS security updates, enable the host firewall with equivalent rules, and configure time synchronization and unattended security updates according to the server operator's policy.
3. Install Docker Engine and the Compose plugin from Docker's official instructions. Confirm `docker compose version`; do not expose the Docker socket over TCP.
4. Create a restricted deployment directory (for example `/opt/agenda-relay`) and a separately protected backup location on durable storage. Ensure the container's uid/gid 10001 can write the application data directory; restrict host access to operator/admin accounts.
5. Configure DNS A (and only a verified AAAA) records. Confirm external resolution before asking Caddy to obtain a certificate.
6. Install and enable Caddy on the host, using the OS vendor's or Caddy's official installation instructions. Keep its config and certificate state owned by the Caddy service account and backed up under the operator's policy.

## Configure DNS, TLS, and reverse proxy

Create `/etc/caddy/Caddyfile` with the real hostname substituted:

```caddyfile
agenda.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:5000
}
```

Validate the Caddyfile and reload Caddy using the host's service manager. Caddy's automatic HTTPS requires correct public DNS and inbound reachability on ports 80 and 443. Verify the certificate from an external network before connecting Google OAuth or sharing booking links. Do not set `PUBLIC_BASE_URL` to an IP, localhost, or development hostname.

Set the application's exact public origin in the protected `.env` file:

```dotenv
APP_ENV=production
PUBLIC_BASE_URL=https://agenda.example.com
PORT=5000
TRUSTED_PROXY_NETWORKS=127.0.0.1/32,::1/128
WHATSAPP_CLOUD_API_ENABLED=false
AUTOMATION_PAUSED=true
AUTO_SEND_SUGGESTIONS=false
AUTO_BOOK_CONFIRMED=false
```

Keep the Compose port binding on `127.0.0.1:5000:5000`; do not change it to `0.0.0.0`. Set long, unique, cryptographically random `FLASK_SECRET_KEY`, `ADMIN_API_TOKEN`, and setup-generated `DATA_ENCRYPTION_KEY`; set `ADMIN_PASSWORD_HASH`; provide an absolute host path for `GOOGLE_CLIENT_SECRETS_FILE_HOST` to a Google OAuth web-client JSON file outside the repository. Keep `.env` and that client file owner-readable only. Use personal-assisted mode unless and until Business API onboarding is separately chosen and authorized.

Register the exact redirect URI `https://agenda.example.com/api/google/callback` in the Google OAuth client before the consent flow. If Meta Business API mode is enabled later, register the webhook URL and verify token only after the authorized configuration and callback verification are ready. The personal-assisted WhatsApp path does not read a personal inbox or send WhatsApp messages.

## Install and start the app

1. Check out the reviewed release/tag or exact commit chosen for deployment into the restricted deployment directory. Do not deploy a moving development branch. Keep the previous release/image available for rollback.
2. Create `.env` with the production values above and secure permissions (`chmod 600 .env`). Create the secret directory outside Git, place the Google client JSON there, and make it read-only to the deployment operator/container as appropriate. Do not use example credentials.
3. Create `data/` on durable encrypted storage and grant only the application/container and administrator accounts the required access. Confirm free disk space and that the filesystem supports SQLite locking.
4. Validate Compose configuration without printing interpolated secrets into logs or CI output; build the image locally on the server or pull the verified immutable release image when a registry/release process exists.
5. Before starting a migrated database, make and verify a separate backup and copy the matching encryption key and Google OAuth token securely. The SQLite file alone is not a complete recovery set.
6. Run the forward-only migration command using the app's configured environment; for example, after the Compose services and env file are prepared, `docker compose run --rm web python -m scheduler.cli migrate`. Review output and verify no unrelated data was mounted.
7. Start both services with `docker compose up -d --build web worker`. Confirm `docker compose ps` reports both healthy/running, `curl --fail http://127.0.0.1:5000/api/health` succeeds on the host, and the authenticated `doctor` command reports database integrity/writability. `doctor` provider readiness may be false while Google OAuth is intentionally disconnected and automation paused.
8. From an external network, verify only HTTPS works for the hostname, the certificate is trusted, the branded login loads, no server/secret detail is exposed, and the app is not reachable directly on port 5000.

Keep Caddy, Docker, and the app host's clocks synchronized. Configure host/service monitoring for disk capacity, memory, service/container restarts, TLS expiry, backup age, and authenticated operator readiness. `/api/health` proves only that the web service answers; it is not provider or booking acceptance.

## Database and data migration

Agenda Relay uses SQLite; it does not use PostgreSQL. Use the app's online backup command rather than copying a live `.sqlite3` file. On a Windows source, choose a protected path:

```powershell
python -m scheduler.cli backup --output C:\safe\agenda.sqlite3
```

On Hetzner, run the command through Compose. Its default destination is under `/app/data/backups`, which maps to the persistent host `./data/backups` directory:

```sh
docker compose run --rm web python -m scheduler.cli backup
```

This creates a local on-host backup only. Configure a separate encrypted, access-controlled off-host copy and restore drills; this repository does not install that schedule.

For a Windows source, stop the web and worker processes after the backup. Transfer the backup, matching `DATA_ENCRYPTION_KEY`, encrypted `GOOGLE_TOKEN_FILE` if migrating a connected account, and Google OAuth client JSON using an approved encrypted channel. Verify hashes on both ends; store keys separately from database backups. Avoid sending credentials through shell command arguments or Git. Do not copy a live SQLite WAL independently of its database.

On the Hetzner host, stop both Compose services, securely place the backup at the configured `DATABASE_PATH`, and ensure the Google token path/key are paired with the same source installation. Start the app with `AUTOMATION_PAUSED=true`. Verify database integrity/schema, run `doctor`, inspect representative records in the operator UI, check timezone and `PUBLIC_BASE_URL`, and perform a read-only Calendar connection check only after OAuth is authorized. Do not send test messages or create/delete real calendar events during migration verification.

After explicit cutover authorization, set the intended DNS TTL/change, register the final Google redirect URI, complete OAuth, and run the authorized end-to-end acceptance matrix. Keep the old installation stopped but intact through the agreed rollback window. A rollback must account for any events created in Google Calendar after cutover; restoring SQLite does not undo provider-side events.

## Backups, retention, monitoring, and recovery

- Run encrypted, access-controlled, off-host database backups on an operator-chosen schedule. Verify each archive and periodically perform a restore drill into an isolated, non-public copy. No backup schedule or Hetzner snapshot automation is installed by this repository.
- Back up the database together with the exact encryption key, Google OAuth client configuration, and recovery instructions, stored separately under access control. Back up Caddy configuration and DNS/firewall settings. Never treat a provider token as recoverable from the SQLite file.
- `SCHEDULING_RETENTION_DAYS` defaults to 90; `DATA_RETENTION_DAYS` governs inbound bodies, rate events, and delivery receipts. Confirm these match the data policy before production and ensure the worker is running.
- Review logs without exporting message bodies or secrets. Support bundles are redacted but still contain operational metadata; inspect and approve them before sharing.
- Check alerting for failed health checks, repeated restarts, worker inactivity, disk pressure, stale backups, TLS problems, failed OAuth/API calls, and unresolved ambiguous bookings. Never automatically replay ambiguous sends or bookings.
- Restore only while web and worker are stopped, using the CLI's explicit confirmation, and only after preserving the current database. The restore command can run without initializing the app, so it can recover a corrupt live database; it preserves unreadable current bytes in a timestamped sidecar safety file. It refuses to replace the database if either SQLite WAL/SHM sidecar remains, even for an empty WAL, so confirm all processes are stopped before investigating or removing stale sidecars. Test the restored copy before routing traffic to it.

## Upgrade and rollback

1. Record the current immutable commit/image, backup, environment version (not secret values), data/key locations, and provider state.
2. Pause automation and create/verify a fresh off-host database and credential recovery backup.
3. Deploy the reviewed immutable version, run migrations, then start and verify health, `doctor`, worker, login, and a read-only UI check.
4. Keep automation paused until the operator confirms configuration and provider state. Resume only after acceptance.
5. If rollback is required, pause automation, stop both services, restore the previous application version and compatible database backup, run integrity/doctor checks, then resume only with operator approval. Check Google Calendar/Meta for side effects before retrying any work. Schema migrations are forward-only; do not expect a binary downgrade to reverse database changes.

## Acceptance before calling production live

The deployment is not production-accepted until an authorized operator verifies DNS/TLS externally, direct-port isolation, secure login, database writeability, backup-and-restore, retention worker, Google OAuth/availability, public booking link from a different device/network, selected-slot recheck, one consented test appointment with cleanup, pause behavior, and the applicable personal-assisted or Business API safeguards. Record exact date, release SHA, test account, and outcomes in a controlled operational record—not this public repository. No real test message, provider send, or Calendar event was created by writing this guide.
