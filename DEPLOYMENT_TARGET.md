# Production deployment target

Hetzner is the target for production deployment. New production deployments must be prepared for Hetzner. Do not use Vercel or local tunnelling services for production ingress.

Before deploying or retiring any existing service, verify the running application, database and persistent data, secrets, security controls, backups and restore procedure, rollback path, DNS, TLS, scheduled work, and external integrations. Do not claim migration or cutover until those checks pass.

See [the Hetzner deployment guide](docs/HETZNER_DEPLOYMENT.md) for the architecture, infrastructure prerequisites, deployment and migration steps, DNS/TLS, secrets, monitoring, backup and rollback procedure. This guide is a deployment plan; no live Hetzner server has been provisioned or changed by these instructions. Keep credentials and private operational data out of source control.

Local development and test tooling may remain when needed, but it must not be presented as production hosting.
