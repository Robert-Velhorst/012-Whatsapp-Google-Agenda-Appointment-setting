# Production deployment target

Hetzner is the target for production deployment. New production deployments must be prepared for Hetzner. Do not use unapproved serverless hosting or public-tunnel services for production.

Before deploying or retiring any existing service, verify the running application, database and persistent data, secrets, security controls, backups and restore procedure, rollback path, DNS, TLS, scheduled work, and external integrations. Do not claim migration or cutover until those checks pass.

Document the Hetzner architecture, required infrastructure, deployment steps, data and database migration, DNS/TLS, secrets, monitoring, backups, and rollback in the project deployment guide before cutover. Keep credentials and private operational data out of this file and source control.

Local development and test tooling may remain when needed, but it must not be presented as production hosting.
