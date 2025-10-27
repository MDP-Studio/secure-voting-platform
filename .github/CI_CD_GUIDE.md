# GitHub CI/CD Workflows

This document describes the automated testing workflows configured for the notAEC voting system.

## Overview

Two workflows are configured to run tests automatically on every push and pull request:

1. **`tests.yml`** - Core unit and integration tests (runs on all branches)
2. **`security-tests.yml`** - WAF and security tests (runs nightly and on main/develop)

## Workflow 1: Core Tests (`tests.yml`)

### When It Runs
- ✅ On every push to: `main`, `develop`, `gotcha`, `feature/**`
- ✅ On every pull request to: `main`, `develop`

### Tests Included
- **Smoke Tests** (`tests/test_smoke.py`): Basic functionality verification
- **Password Tests** (`tests/test_password_validation.py`, `tests/test_password_policy.py`): Password strength validation
- **Integration Tests** (`tests/integration/test_integration.py::TestHealth`): Health checks and basic API functionality

### Configuration
```yaml
Timeout: 15 minutes
Python Version: 3.10
Database: PostgreSQL 15 (in-service)
Environment: FLASK_ENV=testing
```

### What It Validates
✅ App starts correctly
✅ Password policy (12+ chars, uppercase, lowercase, special char)
✅ Basic health checks
✅ Core authentication flows
✅ Database integrity

---

## Workflow 2: Security Tests (`security-tests.yml`)

### When It Runs
- ✅ On every push to: `main`, `develop`
- ✅ On every pull request to: `main`, `develop`
- ✅ Nightly at 2 AM UTC (daily schedule)

### Tests Included
- **WAF Security Tests** (`tests/integration/test_waf_security.py`): OWASP ModSecurity CRS validation
  - SQL injection blocking (7 test cases)
  - XSS prevention (6 test cases)
  - Rate limiting verification
  - Security headers validation
  - Malicious pattern detection

- **Rate Limiting Tests** (`tests/test_vote_rate_limiting.py`): Vote rate limiting validation

### Configuration
```yaml
Timeout: 30 minutes
Python Version: 3.10
Services: Docker Compose (web, WAF, database)
Runs Nightly: 2 AM UTC
```

### What It Validates
✅ WAF properly blocks SQL injections
✅ XSS attacks are prevented
✅ Rate limiting works correctly
✅ Security headers are present
✅ Malicious patterns are detected

---

## Viewing Test Results

### In GitHub UI
1. Navigate to your repository
2. Click the **"Actions"** tab
3. Select a workflow run to see details
4. Click a job to see test output

### Check Status Badge
Add to your README.md:
```markdown
[![Tests](https://github.com/colinwirt/sec-soft-sys-a3/actions/workflows/tests.yml/badge.svg)](https://github.com/colinwirt/sec-soft-sys-a3/actions/workflows/tests.yml)
```

---

## Test Artifacts

Both workflows upload test artifacts (if available):
- Test results (XML format)
- Docker logs (on failure)

**Access artifacts:**
1. In the workflow run details, scroll down to "Artifacts"
2. Download the archive for local analysis

---

## Customizing Workflows

### Add More Tests
Edit `.github/workflows/tests.yml` and add to the test commands:
```yaml
- name: Run Additional Tests
  run: |
    python -m pytest tests/test_your_feature.py -v --tb=short
```

### Modify Test Coverage
To include all integration tests (requires Docker):
```yaml
- name: Run Full Integration Tests
  run: |
    docker-compose up -d
    python -m pytest tests/integration/ -v --tb=short --base-url=http://localhost
    docker-compose down
```

### Change Scheduled Time for Security Tests
Edit `.github/workflows/security-tests.yml` under `schedule`:
```yaml
schedule:
  # Run at 3 AM UTC instead
  - cron: '0 3 * * *'
```

### Branch Filters
Modify `on.push.branches` or `on.pull_request.branches`:
```yaml
on:
  push:
    branches: [ main, staging, "release/**" ]
  pull_request:
    branches: [ main ]
```

---

## Debugging Failed Tests

### Local Reproduction
Run tests locally to match CI environment:

```bash
# Install dependencies
pip install -r requirements-dev.txt

# Set testing environment
export FLASK_ENV=testing
export GEO_FILTER_ENABLED=False
export ENABLE_MFA=False

# Run specific failing test
python -m pytest tests/test_smoke.py::test_app_starts -v --tb=short
```

### Check Workflow Logs
1. Go to Actions → Workflow run
2. Expand the failed step to see full output
3. Look for error messages and stack traces

### Download Artifacts
Failed runs often have artifacts (Docker logs, test results):
1. Go to Actions → Workflow run
2. Scroll to "Artifacts" section
3. Download for local analysis

---

## Best Practices

### ✅ Commit Messages
```
Fix: Update password validation
```
This triggers the full test suite automatically.

### ✅ Pull Request Strategy
- Create PR against `main` to trigger security tests
- Merge to `develop` for feature validation

### ✅ Monitor PR Status
GitHub shows test status directly on PR:
- 🟢 All tests pass → Ready to merge
- 🔴 Tests fail → Fix and push again
- 🟡 Tests running → Wait for completion

### ✅ Keep Tests Fast
- Unit tests: < 30 seconds
- Integration tests: < 5 minutes
- Security tests: < 30 minutes

---

## Troubleshooting

### Tests Timeout
- Increase `timeout-minutes` in workflow
- Check for hung processes in Docker logs
- Reduce number of concurrent tests

### Database Connection Issues
- Verify PostgreSQL service is healthy
- Check `GITHUB_ENV` settings
- Review service configuration

### Docker Service Fails
- Ensure `docker-compose.yml` is valid
- Check disk space on runner
- Review Docker logs: `docker-compose logs`

### Rate Limiting in Tests
- Add delays between requests
- Use test fixtures that reset state
- Reduce concurrent test runs

---

## Next Steps

1. **Commit these workflows** to your repository
2. **Test locally** first before pushing
3. **Monitor the Actions tab** for results
4. **Adjust configurations** as needed
5. **Add more tests** as coverage grows

---

## References

- [GitHub Actions Documentation](https://docs.github.com/actions)
- [pytest Documentation](https://docs.pytest.org/)
- [Docker Compose in CI/CD](https://docs.docker.com/compose/environment-variables/set-environment-variables/)
