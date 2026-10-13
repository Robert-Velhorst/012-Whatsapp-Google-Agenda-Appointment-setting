# Codex checkpoints

| Checkpoint | Status | Resume instruction |
|---|---|---|
| PDF fully inspected | Complete | Requirement titles and common acceptance rules are captured in completion matrix |
| Repository truth recorded | Complete | Current branch `codex/agenda-relay-mainline`; current source-of-truth status is the Git checkout and matching CI runs |
| Domain critical path | Implemented locally; active hardening continues | Run `tests/test_critical_path.py` and `tests/test_webhook.py` after service changes; inbound messages parse independently to prevent stale context from triggering or altering requests |
| Security/privacy | Implemented for single-workspace scope; external assurance incomplete | Preserve HMAC, CSRF, encryption, ownership filters, and production validation; no external penetration test |
| Operator UI | Implemented locally; provider onboarding remains incomplete | Desktop/mobile browser QA exists; Google OAuth and live provider setup still require an operator |
| Worker/reminders | Implemented locally | Keep approved-template/manual-required boundary; verify worker health during source-launcher recovery |
| Deployment | Windows package, Docker, and ngrok launch paths implemented; live provider deployment unverified | CI/package runs apply only to their exact SHA; do not claim Meta/Google/ngrok acceptance without accounts |
| Real provider proof | Not verified | Requires authorized Google credentials, HTTPS/ngrok, consented test contacts, and operator acceptance |
| Final verification | In progress | Keep this checkpoint open until code review, fresh full tests, exact-SHA CI/package, and external acceptance gaps are recorded |
