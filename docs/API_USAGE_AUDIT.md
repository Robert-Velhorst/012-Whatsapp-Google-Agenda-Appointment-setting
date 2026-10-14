# API usage audit

## Public/provider-facing

| Method/path | Caller | Purpose | Protection |
|---|---|---|---|
| `GET /webhook/whatsapp` | Meta | Verification challenge | Exact verify token; endpoint disabled when `WHATSAPP_CLOUD_API_ENABLED=false` |
| `POST /webhook/whatsapp` | Meta | Inbound messages | HMAC, 1 MB limit, dedupe; endpoint disabled when `WHATSAPP_CLOUD_API_ENABLED=false` |
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
| `GET /api/requests`, `/<id>` | Dashboard/API users | Search/filter/paginated requests and detail; page size is 1–100 and page number is clamped to available results |
| `POST /api/proposals/<id>/send` | Dashboard/API users | Rate-limited official WhatsApp send |
| `POST /api/appointments/<id>/book` | Dashboard/API users | Idempotent Google event creation |
| `POST /api/appointments/<id>/cancel` | Dashboard/API users | Calendar cancellation and job stop |
| `GET /api/audit` | Audit view/API users | Workspace-scoped event history, clamped to 1–500 rows |
| `GET /api/contacts/<id>/export` | Privacy workflow | Contact JSON export |
| `DELETE /api/contacts/<id>` | Privacy workflow | Contact/domain-data deletion |
| `GET /api/export/requests.csv` | Dashboard/API users | Workspace CSV export |

The personal WhatsApp screen is session-only (not bearer API): `POST /actions/assisted/analyze` performs transient local analysis and a Calendar availability query, while `POST /actions/assisted/<id>/shared` activates the private booking link only after the operator confirms manual sharing. Both require CSRF and create no WhatsApp API calls.

## External provider calls

- Google `freebusy.query`: real calendar availability.
- Google `events.insert/get/update/delete`: event lifecycle; deterministic event ID handles insert retries.
- Meta Graph `/{phone-number-id}/messages`: text proposals/confirmations and approved reminder templates.
- WhatsApp `https://wa.me/?text=...` is only a browser link with a prefilled draft; the operator must choose a recipient and send. Agenda Relay makes no personal WhatsApp API call.

HTTP 200 from Meta means API acceptance, not confirmed delivery/read. The data model intentionally does not fabricate delivery status because status webhooks are not yet persisted.
