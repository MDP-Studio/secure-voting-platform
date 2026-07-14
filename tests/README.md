# Testing Guide

SecureVote uses pytest for application behaviour, security controls, race
conditions, election-domain integrity, and structural accessibility evidence.
The current collection is 243 tests. A plain local run passes 239 and skips
four opt-in MySQL checks: two raw permission probes, one production-like Flask
split-bind flow, and one populated legacy-schema migration. CI executes all
four against MySQL 8.4 LTS.

## Install and run

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

The CI workflow uses Python 3.12, provisions environment-driven split database
accounts, runs a production-like Flask request flow over both runtime binds,
then runs the normal SQLite-backed application suite plus live MySQL grant
checks. It also validates the Compose configuration, builds the application
image, and performs dependency and high-confidence Bandit scans.

## Test map

| Area | Evidence | Tests |
| --- | --- | ---: |
| Login automation controls | `integration/test_login_robot_blocking.py` | 15 |
| Live MySQL authentication and grants | `integration/test_mysql_permissions.py` | 2 |
| Live MySQL Flask split-bind routing | `integration/test_mysql_flask_split_binds.py` | 1 |
| Live MySQL populated legacy migration | `integration/test_mysql_legacy_migration.py` | 1 |
| Encrypted-field-safe administrator search | `test_admin_encrypted_search.py` | 1 |
| Structured audit completeness and tamper detection | `test_audit_completeness.py` | 3 |
| JWT authority, exact password handling, reset revocation, verification, and redirects | `test_auth_session_security.py` | 18 |
| Election-bound key lifecycle and exploit regression | `test_blind_election_binding.py` | 7 |
| Blind-signature protocol, input bounds, and HTTP flow | `test_blind_signature.py` | 10 |
| Authenticated JSON CSRF enforcement | `test_csrf_json.py` | 3 |
| Request-aware database routing and identity-free ballot binding | `test_database_routing.py` | 8 |
| Deployment, bootstrap, and Vault token safety | `test_deployment_safety.py` | 11 |
| Election scope, UTC schedules, eligibility, roster, and tally integrity | `test_election_integrity.py` | 12 |
| Fresh, legacy, and partial election migration | `test_election_scope_migration.py` | 5 |
| Canonical and enumeration-resistant email delivery | `test_email_delivery_security.py` | 3 |
| Minimal health endpoint disclosure | `test_health_security.py` | 2 |
| Server-side OTP replay and attempt limits | `test_otp_security.py` | 4 |
| Immutable result-signing provenance | `test_result_signing_integrity.py` | 10 |
| Fail-closed hosted runtime configuration | `test_runtime_security_config.py` | 16 |
| Password reset, election access, anonymity, audit UI | `test_new_features.py` | 15 |
| Pagination limits | `test_pagination_security.py` | 2 |
| Account lockout, expiry, and password change | `test_password_policy.py` | 19 |
| Password validation and registration | `test_password_validation.py` | 27 |
| Versioned PII encryption, capacity preflight, migration, tamper, and access control | `test_pii_encryption_and_access.py` | 23 |
| Core application smoke and authorization checks | `test_smoke.py` | 16 |
| Verification rehearsal accessibility and behaviour | `test_verification_ceremony.py` | 7 |
| Concurrent vote race checks | `test_vote_concurrency.py` | 2 |

## Focused commands

```bash
python -m pytest tests/test_blind_signature.py -q
python -m pytest tests/test_blind_election_binding.py -q
python -m pytest tests/test_pii_encryption_and_access.py -q
python -m pytest tests/test_vote_concurrency.py -q
python -m pytest tests/test_election_integrity.py tests/test_result_signing_integrity.py -q
python -m pytest tests/integration/test_login_robot_blocking.py -q
MYSQL_FLASK_INTEGRATION_TEST=1 python -m pytest tests/integration/test_mysql_flask_split_binds.py -q
python -m pytest tests/test_verification_ceremony.py -q
```

## Verification rehearsal coverage

`test_verification_ceremony.py` checks that the public mock ceremony:

- accepts no submitted election result or observer record;
- uses labelled native checkboxes and a native reset button;
- has a single `h1`, logical heading levels, and a main landmark;
- exposes labelled progress and a polite status region;
- documents trust assumptions, failure cases, and non-claims;
- updates progress and completion state and returns focus after reset.

These structural tests do not replace manual assistive-technology testing. The
manual keyboard, NVDA or VoiceOver, zoom, contrast, and reduced-motion checklist
is documented in `docs/VERIFICATION_CEREMONY.md`.

## Environment and fixtures

`conftest.py` creates an isolated temporary SQLite database and deterministic test
users, roles, candidates, enrolment, and election state. The encryption key in
that fixture is test-only and must never be used outside the suite.

The normal fixture remains SQLite. CI separately starts MySQL and executes two
account/grant tests, one production-like Flask split-bind test, and one
populated legacy-schema migration. The request-flow test casts a ballot while
a manager cookie is attached, proves the endpoint still uses the voter
credential, updates a draft roster with the admin credential, and asserts the
migration engine executes no request SQL. The Docker WAF, live Vault, real SMTP
delivery, and browser assistive technologies still require deployment-specific
verification.

## Interpreting failures

- A failed security-control test blocks delivery until fixed or documented as an
  environment limitation.
- Do not convert failing assertions into empty, skipped, or permissive tests.
- Keep the expected warning about the missing local GeoIP City database separate
  from test failures. The repository includes only the country database.
- Keep the developer-dashboard network boundary covered without introducing
  environment-dependent skips.
