# SecureVote — Secure Electronic Voting Platform

A secure online voting platform built with Flask, featuring cryptographic voter anonymity via RSA blind signatures, PII encryption at rest, multi-factor authentication, Web Application Firewall integration, and result signing via HashiCorp Vault.

Built as part of a Secure Software Systems course — originally a team project, completed and enhanced as a solo portfolio piece.

## Key Security Features

- **RSA Blind Signatures** — The server signs ballots without seeing their contents. Votes are cast anonymously via a separate endpoint with no cookies or session data (Chaum 1983, Bellare-Rogaway 1996 FDH proof)
- **CSRF Protection** — Per-session tokens validated on all state-changing requests with constant-time comparison
- **PII Encryption at Rest** — Voter personal data encrypted with ChaCha20-Poly1305 (AEAD)
- **Blind Indexing** — Driver licence lookups use HMAC-SHA256 with high-entropy pepper
- **Web Application Firewall** — OWASP ModSecurity CRS via nginx reverse proxy
- **Cryptographic Result Signing** — Election results signed via HashiCorp Vault Transit engine (non-repudiation)
- **HMAC-Backed Audit Logging** — Tamper-evident audit trail with chain verification
- **Role-Based Access Control** — Voter, Delegate, Manager roles with enforced permissions
- **Account Security** — Lockout after 5 failed attempts, 90-day password expiry, 12-char minimum with complexity requirements
- **Two-Step MFA** — Server-enforced email OTP after password validation (separate page, not client-bypassable)
- **Pessimistic Locking** — `SELECT ... FOR UPDATE` + `VoteReceipt(UNIQUE user_id)` prevents TOCTOU double-voting
- **Geo-IP Filtering** — Country-level access restriction via MaxMind GeoIP2
- **Rate Limiting** — Per-endpoint WAF limits (voting: 2 req/min, general: 500 req/min)
- **Election State Management** — Draft/open/close lifecycle with time-based enforcement

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Flask 2.3, SQLAlchemy, Flask-Login, Flask-Mail, Flask-Migrate |
| Database | MySQL 8.0 (production) / SQLite (development) |
| Security | ChaCha20-Poly1305, RSA blind signatures, PyJWT, itsdangerous, HashiCorp Vault |
| Infrastructure | Docker Compose, nginx + ModSecurity, Gunicorn |
| Testing | pytest (103 tests), GitHub Actions CI/CD |
| Frontend | Jinja2, Bootstrap 5, Inter font, Web Speech API |

## Architecture

```
                    +-----------+
  Users ──────────► |  nginx    |  WAF (ModSecurity CRS)
                    |  :80      |  Rate Limiting, Security Headers
                    +-----+-----+
                          │
                    +-----v-----+
                    |  Flask    |  Authentication, RBAC, Encryption
                    |  :8000    |  Business Logic, Blind Signatures
                    +-----+-----+
                          │
              +-----------+----------+
              │                      │
        +-----v-----+        +------v------+
        |  MySQL    |        |  Vault      |
        |  :3306    |        |  :8200      |
        |  Split    |        |  Transit    |
        |  Binds    |        |  KV v2      |
        +-----------+        +-------------+
```

**Split Database Connections:** Admin and voter operations route to separate MySQL users with different permission sets, enforced at the ORM session level.

### Anonymous Voting Protocol (RSA Blind Signatures)

```
Phase 1 — Authenticated (server sees voter, NOT ballot):
  Voter ──[blinded ballot]──► Server signs blind data
                               Issues VoteReceipt (UNIQUE user_id)
  Voter ◄──[blind signature]── Server never sees candidate choice

Phase 2 — Anonymous (server sees ballot, NOT voter):
  Voter unblinds signature (client-side BigInt math)
  Random 5-30s delay (timing attack mitigation)
  Voter ──[ballot + signature]──► /vote/cast (NO cookies, NO session)
                                   Server verifies signature
                                   Stores anonymous Vote record
```

The server signs the ballot without seeing its contents. The voter casts the ballot without revealing their identity. Even a fully compromised server cannot link votes to voters — the cryptographic blinding makes the two phases unlinkable.

## Quick Start

### Local Development (SQLite)

```bash
pip install -r requirements.txt
python run_demo.py
# Access: http://localhost:5000
```

### Docker (Full Stack)

```bash
cp .env.example .env   # Fill in your secrets
docker-compose up --build -d
# Web (WAF-protected): http://localhost
# Vault UI: http://localhost:8200
```

### Default Test Credentials

| Role | Username | Password |
|------|----------|----------|
| Manager | admin | Admin@123456! |
| Delegate | delegate1 | Delegate@123! |
| Voter | voter1 | Password@123! |

## Features

### Voter Flow
1. Register with driver licence and identity verification
2. Email verification link sent automatically
3. Admin reviews and approves account
4. Log in → two-step MFA challenge (if enabled)
5. Cast anonymous vote via blind signature protocol
6. View confirmation — ballot cannot be traced to voter

### Manager Flow
- Approve/reject user registrations (email verification status visible)
- Unlock locked accounts
- Create and manage elections (draft → open → close lifecycle)
- View vote tallies and sign results cryptographically
- Review HMAC-backed audit log with chain integrity verification

### Delegate Flow
- Manage candidates within assigned region (region guards enforced)
- View regional electoral roll data

### Accessibility
- **Text-to-Speech** — Floating TTS button (bottom-right) using the browser's Web Speech API. Click any text to hear it read aloud, or "Read Page" for full content. Keyboard shortcut: `Alt+T`
- **Skip-to-content** link, ARIA landmarks, focus indicators
- **Reduced motion** and **high contrast** mode support

### Security Controls
- Password reset via signed, time-limited email tokens (30-min expiry)
- Generic responses to prevent email enumeration
- CSRF tokens on all POST forms
- GOTCHA honeypot fields + login nonce consumption tracking
- Cloudflare Turnstile integration (optional)
- Content Security Policy, X-Frame-Options, HSTS headers via nginx

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v    # 103 tests, all pass
```

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_smoke.py` | 14 | Core: login, voting, dashboard, results, logout |
| `test_blind_signature.py` | 8 | RSA blind signature protocol + full HTTP flow |
| `test_new_features.py` | 14 | Password reset, profile, elections, errors, anonymity |
| `test_password_validation.py` | 25 | Password strength rules + edge cases |
| `test_password_policy.py` | 8 | Account lockout, password expiry |
| `test_vote_concurrency.py` | 2 | 10-thread TOCTOU stress test |
| `test_pii_encryption_and_access.py` | 3 | PII encryption at rest + access control |
| `test_pagination_security.py` | 2 | Pagination limit enforcement |
| `integration/test_login_robot_blocking.py` | 2 | Anti-bot nonce validation |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Flask session secret | `dev-secret` |
| `DATABASE_URL` | Database connection string | SQLite (local) |
| `VOTER_PII_KEY_BASE64` | 32-byte Base64 encryption key | Auto-generated |
| `LICENSE_HASH_PEPPER` | High-entropy pepper for blind indexing | — |
| `ENABLE_MFA` | Enable email-based OTP | `False` |
| `GEO_FILTER_ENABLED` | Enable IP geo-filtering | `True` |
| `VAULT_ADDR` / `VAULT_TOKEN` | HashiCorp Vault connection | — |
| `MAIL_USERNAME` / `MAIL_PASSWORD` | SMTP credentials for emails | — |
| `AUDIT_HMAC_KEY` | HMAC key for audit log chain integrity | — |

See `.env.example` for the full list with generation instructions.

## Documentation

- [Password Policy](docs/PASSWORD_POLICY.md) — Account lockout, expiration, strength rules
- [Vault Setup](docs/VAULT_SETUP.md) — Transit engine and KV integration
- [Environment Detection](docs/ENVIRONMENT_DETECTION.md) — Production safety system
- [CI/CD Guide](.github/CI_CD_GUIDE.md) — Workflow documentation

## License

[MIT](LICENSE)
