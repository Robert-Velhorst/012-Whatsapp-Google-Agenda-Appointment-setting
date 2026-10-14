# Codex checkpoints

| Checkpoint | Status | Resume instruction |
|---|---|---|
| PDF fully inspected | Complete | Requirement titles and common acceptance rules are captured in completion matrix |
| Repository truth recorded | Complete | Unborn `main`; no starting commit; origin is supplied empty repository |
| Domain critical path | Complete locally | Run `test_critical_path.py` before any refactor |
| Security/privacy | Complete for single-workspace scope | Preserve HMAC, CSRF, encryption, ownership filters, and production validation |
| Operator UI | Complete locally | Desktop/mobile browser QA passed; preserve the tested application shell |
| Worker/reminders | Complete locally | Keep approved-template/manual-required boundary |
| Deployment | Hetzner runbook prepared, live cloud deployment not performed | Docker and Windows package evidence is local/CI only; verify DNS, firewall, TLS, backups, and Google/provider acceptance on an authorized Hetzner host |
| Real provider proof | Blocked | Requires Meta/Google credentials, HTTPS, approvals, and consented accounts |
| Final verification | Pending current commit CI | Windows 11 standalone package and launcher self-check passed locally; refresh full tests and exact-SHA CI/package workflows for the current tip; retain separate Hetzner, Google/provider, and HAI acceptance gates |
