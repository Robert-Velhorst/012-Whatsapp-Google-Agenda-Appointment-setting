# Maintenance plan and debt register

## Routine

- Weekly: review failed/manual jobs, audit unusual auth/provider events, verify backups.
- Monthly: rotate short-lived provider tokens where applicable, test restore in isolation, review Meta template status and Google OAuth consent.
- Quarterly: update pinned dependencies after test/Docker scans, run real critical path, review retention/privacy requests, re-evaluate provider policies.

## Technical debt

1. SQLite and one worker fit a small single-operator deployment, not horizontally scaled SaaS.
2. Browser UI is English; intent and contact replies support Dutch/English.
3. Team roles, SSO, per-user sessions, and per-workspace credentials are not implemented.
4. WhatsApp delivery/read status webhooks are not stored.
5. Rescheduling an already-booked event is available at provider-adapter level but not exposed as a reviewed UI state machine.
6. Contact deletion is API-only and should gain a re-authenticated confirmation UI.
7. PostgreSQL/distributed locks are required before multi-instance worker deployment.

## Roadmap

P1: real-provider rehearsal, delivery-status webhooks, token expiry, reschedule review flow, re-authenticated privacy UI.
P2: Postgres, durable distributed queue/rate limits, organization SSO/RBAC, per-workspace provider vault.
P3: optional privacy-reviewed AI intent provider, travel-time provider, analytics and localization beyond EN/NL.
