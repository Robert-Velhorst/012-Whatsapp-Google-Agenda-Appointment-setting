# Deployment target

For this project, the required cloud-access mode is the single-operator Windows 11 application exposed through the operator's assigned ngrok HTTPS domain. For personal WhatsApp assisted mode, the tunnel makes private booking links and Google OAuth callbacks reachable; it does not connect to or automate the personal WhatsApp account. If the optional Business Cloud API is enabled, the tunnel also carries its signed webhook.

The deployment remains single-host and single-instance. Do not describe it as highly available or suitable for horizontally scaled SaaS. Before opening the tunnel, require `APP_ENV=production`, strong non-default secrets, Google OAuth client configuration, a valid exact `PUBLIC_BASE_URL`, a dedicated ngrok inspector port bound to loopback, and a passing authenticated `public_ingress` readiness check. Meta credentials are additionally required only when `WHATSAPP_CLOUD_API_ENABLED=true`. Verify the assigned HTTPS hostname and public health response before sharing booking links or registering provider callbacks.

Keep the HAI JSON feed local and owner-scoped. Never expose it through ngrok or another public tunnel; use loopback or a narrowly allowlisted local Docker Desktop gateway as documented in [HAI integration](docs/HAI_INTEGRATION.md).

The ngrok account, assigned domain, available endpoint slot, provider credentials and approvals, and real-account acceptance are operator-controlled external requirements. No tunnel, provider account, or Google Calendar event is considered live-ready until the operator completes and verifies those steps.
