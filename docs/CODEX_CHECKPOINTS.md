# Codex checkpoints

| Checkpoint | Status | Resume instruction |
|---|---|---|
| PDF fully inspected | Complete | Requirement titles and common acceptance rules are captured in completion matrix |
| Repository truth recorded | Complete | Unborn `main`; no starting commit; origin is supplied empty repository |
| Domain critical path | Complete locally | Run `test_critical_path.py` before any refactor |
| Security/privacy | Complete for single-workspace scope | Preserve HMAC, CSRF, encryption, ownership filters, and production validation |
| Operator UI | Complete locally | Desktop/mobile browser QA passed; preserve the tested application shell |
| Worker/reminders | Complete locally | Keep approved-template/manual-required boundary |
| Deployment | Hetzner runbook prepared, live cloud deployment not performed; ngrok is not a supported or required path | Docker and Windows package evidence is local/CI only; verify DNS, firewall, TLS, backups, and Google/provider acceptance on an authorized Hetzner host |
| Real provider proof | Blocked | Requires Meta/Google credentials, HTTPS, approvals, and consented accounts |
| Final verification | Exact pushed tip `b685f14bc3180450da891eee7f7a9a1206dba0c6` passed both Verify jobs, Python and Actions analysis, CodeQL, and the Windows package build/smoke workflow on 2026-10-14 | Local full suite: 263 passed; compileall and pip check passed. Keep live Hetzner and Google/provider acceptance open. The separate local-only HAI cursor patch passes focused Go tests and vet; Postgres integration remains untested because no dedicated test DSN or responsive local Postgres runtime is available |
