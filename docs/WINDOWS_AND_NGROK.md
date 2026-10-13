# Windows 11 and ngrok

## Standalone Windows package

`AgendaRelay-Windows-x64.zip` contains a self-contained `AgendaRelay.exe`; the target Windows 11 computer does not need Python. Extract the archive to a durable folder, copy `.env.example` to `.env`, fill in the provider and security settings, then start `AgendaRelay.exe`. It runs the web application and due-job worker together and listens on loopback by default.

The source distribution also includes guided launchers:

```powershell
.\windows\Install-AgendaRelay.ps1
.\windows\Start-AgendaRelay.ps1 -OpenBrowser
.\windows\Stop-AgendaRelay.ps1
```

The source launcher refuses to start if its port is already occupied. When recovering an existing run, it verifies that recorded process IDs still belong to the expected Agenda Relay executables and command lines, checks the web health endpoint, and restarts a missing worker without launching a duplicate web server. The stop script likewise leaves unrelated or PID-reused processes untouched. Runtime state, SQLite data, and logs stay below `data/` and are excluded from Git. The Windows workflow tests launcher identity/recovery decisions and builds and smoke-tests the packaged executable on version tags and manual runs.

## Local testing and operator acceptance through ngrok

This tunnel is an optional way to test public booking links and complete Google OAuth while the application runs on a Windows computer. It is not production hosting or an approved production ingress path. Hetzner is the production target; do not use ngrok for production.

Install and authenticate the current ngrok agent, then assign a stable domain to this application. Configure:

```dotenv
APP_ENV=production
PUBLIC_BASE_URL=https://your-assigned-domain.ngrok.app
NGROK_DOMAIN=your-assigned-domain.ngrok.app
NGROK_INSPECTOR_PORT=4042
```

All production secrets, Google client JSON, operator password hash, and encryption key must also be valid. Meta credentials are required only when `WHATSAPP_CLOUD_API_ENABLED=true`. In personal-only mode, the HTTPS tunnel serves private booking links and the Google OAuth callback; it does not connect to your WhatsApp account. Start Agenda Relay first, then run:

```powershell
.\windows\Start-Ngrok.ps1
```

The launcher refuses public exposure unless production-mode configuration and the selected integration mode pass the protected local `public_ingress` check. Production-mode configuration here is a safety gate, not an indication that this is production deployment. When WhatsApp Cloud API is enabled, valid webhook credentials are required. When it is disabled, no WhatsApp webhook is accepted and the tunnel supports the assisted personal flow and private booking links without Meta credentials. When Google OAuth is not connected, ingress is allowed only while automation is paused so the operator can complete consent safely. The ordinary scheduling readiness endpoint remains false until Google is connected and automation is resumed. Test real Google Calendar access and public booking-link reachability before using the workflow.

The launcher requires the operator API token to read this local ingress check; it does not send that token through ngrok. It uses a project-specific local inspector port, verifies the exact assigned HTTPS URL, calls the public health endpoint, and records the verified process before reporting success. Stop only this tunnel with `.\windows\Stop-Ngrok.ps1`.

Register these exact provider URLs only after verification:

- Meta callback: `${PUBLIC_BASE_URL}/webhook/whatsapp`
- Google OAuth redirect: `${PUBLIC_BASE_URL}/api/google/callback`

An ngrok account can impose endpoint/session limits. If another endpoint already owns the requested domain, the launcher fails and leaves it untouched. Do not enable endpoint pooling for unrelated applications.

## HAI on the same Windows host

Keep the HAI feed off the public tunnel. Enable it only on loopback and point HAI's `json-feed` connector at `http://127.0.0.1:<PORT>/api/integrations/hai/feed`. See `docs/HAI_INTEGRATION.md` for the Docker Desktop gateway variant and network allowlist.
