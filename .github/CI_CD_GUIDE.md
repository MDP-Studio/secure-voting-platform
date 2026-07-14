# CI verification guide

The repository has one required workflow: `.github/workflows/tests.yml`. It
runs for pushes and pull requests to `main`.

## What CI proves

- Installs version-constrained runtime and development requirements.
- Starts MySQL 8.4.
- Applies the full Alembic migration chain.
- Provisions separate voter and administrator database users.
- Runs the real-MySQL permission and split-bind request tests.
- Runs the complete pytest suite.
- renders the Docker Compose configuration and builds the application image.
- Checks Vault bootstrap shell syntax.
- Audits both requirement files with `pip-audit`.
- Runs high-severity, high-confidence Bandit checks.

## What CI does not prove

CI does not start the complete Compose stack. It therefore does not claim live
ModSecurity blocking, nginx rate limiting, Vault Transit availability, real
SMTP delivery, TLS termination, browser accessibility, backup restoration, or
production infrastructure readiness. Those are explicit pre-deployment gates.

## Local parity

```bash
python -m pytest -q
python -m pip_audit -r requirements.txt
python -m pip_audit -r requirements-dev.txt
python -m bandit -r app scripts -lll -iii
docker compose config --quiet
docker build --file app/Dockerfile --tag securevote:local .
sh -n scripts/vault-init.sh
```

Docker-dependent commands require a running Docker daemon. A hosted release
must additionally start the full stack in a disposable environment and prove
representative CRS blocking, rate limits, canonical email URLs, SMTP delivery,
Vault signing, migration/restore, and health checks before any real use.
