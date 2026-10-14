# Windows 11 standalone setup

Agenda Relay can run locally on Windows 11 as either a self-contained executable or a Python source installation. This path is intended for local operator use and testing. It does not expose the app publicly, provide hosted availability, or replace the Hetzner production deployment.

## Standalone package

`AgendaRelay-Windows-x64.zip` contains `AgendaRelay.exe`; the target computer does not need Python. Extract the archive to a durable folder, copy `.env.example` to `.env`, complete the local security and provider settings, then start `AgendaRelay.exe`. The executable reads `.env` beside itself and resolves relative database, token, and Google OAuth client paths from the package folder. It runs the web application and due-job worker together and listens on loopback by default.

## Source installation

Install Python 3.11–3.13, then run:

```powershell
.\windows\Install-AgendaRelay.ps1
.\windows\Start-AgendaRelay.ps1 -OpenBrowser
```

Stop only the processes owned by this installation with:

```powershell
.\windows\Stop-AgendaRelay.ps1
```

The source launcher refuses to start if its port is occupied. During recovery it verifies recorded process IDs against the expected executables and command lines, checks web health, and can restart a missing worker without duplicating the web server. The stop script leaves unrelated or PID-reused processes untouched. Runtime state, SQLite data, and logs remain under `data/` and are excluded from Git.

## Local access and privacy

Keep the Windows installation on loopback unless using a separately reviewed and authorized hosting design. `PUBLIC_BASE_URL` should remain local for ordinary development. Do not expose a development computer directly to the internet or use a tunnel to substitute for the supported Hetzner production ingress.

For personal WhatsApp, the operator pastes only the relevant consented message text, reviews the generated proposal, opens WhatsApp manually, and sends the draft. The app does not connect to a personal WhatsApp inbox and does not send personal WhatsApp messages. Real Google Calendar functionality requires an authorized OAuth client and consent. See [operator runbook](OPERATOR_RUNBOOK.md), [privacy/security](SECURITY.md), and [acceptance tests](ACCEPTANCE_TESTS.md).
