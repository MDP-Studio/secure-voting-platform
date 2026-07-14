# CI and deployment verification boundaries

## Implemented

- One push/PR workflow with MySQL 8.4, migrations, least-privilege database
  provisioning, real split-bind requests, the full pytest suite, dependency
  audit, Bandit, Compose rendering, image build, and shell syntax checks.
- SHA-pinned third-party GitHub Actions.
- A maintenance-profile migration runner that holds the schema-owner credential
  while the web runtime keeps only voter/admin application credentials.
- Fail-closed hosted configuration for HTTPS cookies, canonical public origin,
  trusted hosts, SMTP transport, MFA, stable cryptographic secrets, and no
  developer routes.

## Deliberately not claimed

The workflow builds but does not start the WAF/Vault/SMTP stack. Live CRS
blocking, nginx rate limiting, TLS, SMTP, Vault Transit, browser accessibility,
backup restoration, and production observability are not CI-proven. They must
be exercised in a disposable release environment before deployment.

## Next infrastructure gate

Add an isolated end-to-end job only when it can safely provide all required
secrets and teardown. That job should:

1. Start the complete Compose stack with blocking-mode ModSecurity.
2. Wait for database migration, Vault initialization, and application health.
3. Prove benign traffic passes and representative injection traffic is blocked.
4. Prove account email uses the canonical origin through a test SMTP sink.
5. Prove Vault result signing and verification.
6. Restore a disposable backup and repeat readiness checks.

Until that job exists and is green, this repository remains a security
engineering prototype rather than a production election platform.
