# Codex checkpoints

| Checkpoint | Status | Resume instruction |
|---|---|---|
| PDF fully inspected | Complete | Requirement titles and common acceptance rules are captured in completion matrix |
| Repository truth recorded | Complete | Unborn `main`; no starting commit; origin is supplied empty repository |
| Domain critical path | Complete locally | Run `test_critical_path.py` before any refactor |
| Security/privacy | Complete for single-workspace scope | Preserve HMAC, CSRF, encryption, ownership filters, and production validation |
| Operator UI | Complete locally | Desktop/mobile browser QA passed; preserve the tested application shell |
| Worker/reminders | Complete locally | Keep approved-template/manual-required boundary |
| Deployment | Local runtimes complete, live provider deployment blocked | Docker and Windows package passed; do not claim Meta/Google/ngrok acceptance without accounts |
| Real provider proof | Blocked | Requires Meta/Google credentials, HTTPS, approvals, and consented accounts |
| Final verification | Pending current commit CI | Windows 11 standalone package and launcher self-check passed locally; Python suite passed 112 tests. Push the documented current branch tip, confirm exact-SHA CI/package workflows, and retain the separate Google/HAI/ngrok live-acceptance gate |
