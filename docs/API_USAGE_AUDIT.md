# API usage audit

## Public/provider-facing

| Method/path | Caller | Purpose | Protection |
|---|---|---|---|
| `GET /webhook/whatsapp` | Meta | Verification challenge | Exact verify token |
| `POST /webhook/whatsapp` | Meta | Inbound messages | HMAC, 1 MB limit, dedupe |
| `GET /book/<token>` | Contact | View offered slots | 256-bit private token, no-store |
| `POST /book/<token>` | Contact | Confirm one slot | Token, proposal state, explicit consent |
| `GET /api/health` | Infrastructure | Process liveness | No sensitive data |
| `GET /api/readiness` | Infrastructure | Minimal readiness | No credential names/details |

## Operator

All operator endpoints require bearer token or authenticated session. Session state changes also require CSRF.

| Method/path | Used by | Result |
|---|---|---|
| `GET /api/operator/readiness` | Settings/doctor-equivalent client | Provider/config detail without secret values |
| `GET /api/google/connect`, callback | Settings | OAuth connection and encrypted token storage |
| `GET /api/requests`, `/<id>` | Dashboard/API users | Search/filter/paginated requests and detail |
| `POST /api/proposals/<id>/send` | Dashboard/API users | Rate-limited official WhatsApp send |
| `POST /api/appointments/<id>/book` | Dashboard/API users | Idempotent Google event creation |
| `POST /api/appointments/<id>/cancel` | Dashboard/API users | Calendar cancellation and job stop |
| `GET /api/audit` | Audit view/API users | Workspace-scoped event history |
| `GET /api/contacts/<id>/export` | Privacy workflow | Contact JSON export |
| `DELETE /api/contacts/<id>` | Privacy workflow | Contact/domain-data deletion |
| `GET /api/export/requests.csv` | Dashboard/API users | Workspace CSV export |

## External provider calls

- Google `freebusy.query`: real calendar availability.
- Google `events.insert/get/update/delete`: event lifecycle; deterministic event ID handles insert retries.
- Meta Graph `/{phone-number-id}/messages`: text proposals/confirmations and approved reminder templates.

HTTP 200 from Meta means API acceptance, not confirmed delivery/read. The data model intentionally does not fabricate delivery status because status webhooks are not yet persisted.
