# Testing Guide

SecureVote uses pytest for application behaviour, security controls, race
conditions, and structural accessibility evidence. The current collection is 112
tests. One legacy developer-dashboard network test is explicitly skipped because
Flask's local test client cannot reproduce the real remote-address boundary.

## Install and run

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

The CI workflow uses Python 3.12 and runs the same suite on pushes and pull
requests to `main`.

## Test map

| Area | Evidence | Tests |
| --- | --- | ---: |
| Login automation controls | `integration/test_login_robot_blocking.py` | 15 |
| Blind-signature protocol and HTTP flow | `test_blind_signature.py` | 8 |
| Password reset, election access, anonymity, audit UI | `test_new_features.py` | 14 |
| Pagination limits | `test_pagination_security.py` | 2 |
| Account lockout, expiry, and password change | `test_password_policy.py` | 19 |
| Password validation and registration | `test_password_validation.py` | 26 |
| PII encryption and access control | `test_pii_encryption_and_access.py` | 3 |
| Core application smoke and authorization checks | `test_smoke.py` | 16 |
| Verification rehearsal accessibility and behaviour | `test_verification_ceremony.py` | 7 |
| Concurrent vote race checks | `test_vote_concurrency.py` | 2 |

## Focused commands

```bash
python -m pytest tests/test_blind_signature.py -q
python -m pytest tests/test_pii_encryption_and_access.py -q
python -m pytest tests/test_vote_concurrency.py -q
python -m pytest tests/integration/test_login_robot_blocking.py -q
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

The Docker WAF, MySQL, Vault, real SMTP delivery, and browser assistive
technologies are outside the local pytest fixture. Verify those boundaries
separately before making deployment or accessibility claims.

## Interpreting failures

- A failed security-control test blocks delivery until fixed or documented as an
  environment limitation.
- Do not convert failing assertions into empty, skipped, or permissive tests.
- Keep the expected warning about the missing local GeoIP City database separate
  from test failures. The repository includes only the country database.
- Review the single existing skip in `test_smoke.py` before changing the
  developer-dashboard network boundary.
