# Windows 11 and ngrok

## Standalone Windows package

`AgendaRelay-Windows-x64.zip` contains a self-contained `AgendaRelay.exe`; the target Windows 11 computer does not need Python. Extract the archive to a durable folder, copy `.env.example` to `.env`, fill in the provider and security settings, then start `AgendaRelay.exe`. It runs the web application and due-job worker together and listens on loopback by default.

The source distribution also includes guided launchers:

```powershell
.\windows\Install-AgendaRelay.ps1
.\windows\Start-AgendaRelay.ps1 -OpenBrowser
.\windows\Stop-AgendaRelay.ps1
```

The source launcher refuses to start if its port is already occupied. Runtime state, SQLite data, and logs stay below `data/` and are excluded from Git. The packaged executable is built and smoke-tested by `.github/workflows/windows-package.yml` on version tags and manual runs.

## Public HTTPS through ngrok

Install and authenticate the current ngrok agent, then assign a stable domain to this application. Configure:

```dotenv
APP_ENV=production
PUBLIC_BASE_URL=https://your-assigned-domain.ngrok.app
NGROK_DOMAIN=your-assigned-domain.ngrok.app
NGROK_INSPECTOR_PORT=4042
```

All production secrets, Meta credentials, Google client JSON, operator password hash, and encryption key must also be valid. Start Agenda Relay first, then run:

```powershell
.\windows\Start-Ngrok.ps1
```

The launcher refuses public exposure unless production validation and local readiness both pass. It uses a project-specific local inspector port, verifies the exact assigned HTTPS URL, calls the public health endpoint, and records the verified process before reporting success. Stop only this tunnel with `.\windows\Stop-Ngrok.ps1`.

Register these exact provider URLs only after verification:

- Meta callback: `${PUBLIC_BASE_URL}/webhook/whatsapp`
- Google OAuth redirect: `${PUBLIC_BASE_URL}/api/google/callback`

An ngrok account can impose endpoint/session limits. If another endpoint already owns the requested domain, the launcher fails and leaves it untouched. Do not enable endpoint pooling for unrelated applications.

## HAI on the same Windows host

Keep the HAI feed off the public tunnel. Enable it only on loopback and point HAI's `json-feed` connector at `http://127.0.0.1:<PORT>/api/integrations/hai/feed`. See `docs/HAI_INTEGRATION.md` for the Docker Desktop gateway variant and network allowlist.
