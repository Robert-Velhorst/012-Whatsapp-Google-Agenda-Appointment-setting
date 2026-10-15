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
| Final verification | Verified source commit `c4d1e329eaac6f9c0d90eb06d65b517a0d8df83c` passed Verify, Python and Actions analysis, CodeQL, and the Windows package/smoke workflow on 2026-10-15 | Current local strict suite: 301 passed; compileall, `pip check`, and Compose-model assertions passed. Windows 11 package and smoke test passed (ZIP SHA-256 `B28F2507BBA10F04CF9C97262F47AA3A094645A214B9C0578D4391EB7B1E5A23`). The separate local-only HAI cursor patch passes `go test ./...` and `go vet ./...` on Go 1.27.2; guarded PostgreSQL integration is skipped because `HAI_ACCOUNT_FEED_TEST_DSN` is unset. Keep live Hetzner and Google/provider acceptance open; Docker daemon did not respond locally. |
