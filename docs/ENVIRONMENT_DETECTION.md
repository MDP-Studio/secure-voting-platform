# Environment Detection System

## Overview

The application now includes a robust **Environment Detection System** to prevent test features from being accidentally enabled in production. This ensures that test-only functionality (like disabled login checks, test data seeding, and developer dashboards) are only available in safe environments.

## Architecture

### Environment Types

The system recognizes five environment types:

1. **Production** - Deployed production environment (should never have test features)
2. **Staging** - Pre-production staging environment (production-like, no test features)
3. **Development** - Development/QA environment (test features enabled)
4. **Local** - Local development machine (test features enabled)
5. **Testing** - Automated test execution (test features enabled)

### Detection Hierarchy

The `EnvironmentDetector` class uses a priority-based detection system:

```
1. DEPLOYMENT_ENV environment variable (highest priority)
   └─ If set to 'production', 'staging', 'development', 'local', or 'testing'
   
2. FLASK_ENV environment variable
   └─ Maps 'production' → production, 'development' → development, others → local
   
3. Production Indicators (environment variables)
   └─ DATABASE_URL pointing to cloud database
   └─ HEROKU_APP_NAME (Heroku deployment)
   └─ AWS_REGION (AWS deployment)
   └─ GOOGLE_CLOUD_PROJECT (GCP deployment)
   └─ AZURE_SUBSCRIPTION_ID (Azure deployment)
   
4. Default: LOCAL (allows test features during development)
```

## Implementation Details

### Module: `app/environment.py`

**Key Classes:**
- `Environment` (Enum) - Defines the five environment types
- `EnvironmentDetector` - Main detection class with production indicator checks

**Key Functions:**
- `get_environment_detector()` - Returns singleton EnvironmentDetector instance
- `is_safe_for_test_features()` - **TRUE** for Local/Development/Testing, **FALSE** for Production/Staging
- `is_production()` - Detects if running in production environment
- `get_current_environment()` - Returns current environment type

### Safety Guarantees

The `is_safe_for_test_features()` function provides strict safety:

```python
def is_safe_for_test_features():
    """
    Returns True only for Local/Development/Testing environments.
    Raises RuntimeError if production tries to enable test features.
    """
    env = get_environment_detector().get_environment()
    
    if env in [Environment.LOCAL, Environment.DEVELOPMENT, Environment.TESTING]:
        return True  # Safe to enable test features
    elif env == Environment.STAGING:
        # Staging should not have test features
        return False
    elif env == Environment.PRODUCTION:
        # CRITICAL: Never allow test features in production
        raise RuntimeError("Cannot enable test features in production environment")
```

## Integration Points

### 1. Authentication (`app/auth.py`)

Login security checks are now gated by environment detection:

```python
# Before: Used simple TESTING flag
if not current_app.config.get('TESTING', False):
    # check nonce, CAPTCHA, etc.

# After: Uses environment detection
skip_security_checks = is_safe_for_test_features()
if not skip_security_checks:
    # check nonce, CAPTCHA, etc. - ALWAYS in production/staging
```

**Impact:** Login security is always enforced in production and staging environments, even if test flags are accidentally set.

### 2. Database Initialization (`app/init_db.py`)

Test voter creation is now gated:

```python
# Before: Only checked CREATE_TEST_VOTERS env var
if create_test_voters and TEST_VOTERS_AVAILABLE:
    # create 100 test voters

# After: Also checks environment safety
if create_test_voters and TEST_VOTERS_AVAILABLE and is_safe_for_test_features():
    # create 100 test voters
```

**Impact:** 100 test voters won't be created in production databases, even if CREATE_TEST_VOTERS is somehow set.

### 3. Developer Routes (`app/routes/dev_routes.py`)

Developer dashboard and logs endpoints now have environment safety checks:

```python
@dev.route('/dashboard')
def dev_dashboard():
    if is_production():
        return "Access denied: Developer dashboard is not available in production", 403
    # ... rest of dashboard code
```

**Impact:** Developer dashboard is completely blocked in production, with logged error attempts.

## Environment Configuration

### Setting the Environment

**Option 1: DEPLOYMENT_ENV (Recommended)**
```bash
# Development/Local
DEPLOYMENT_ENV=local

# Staging
DEPLOYMENT_ENV=staging

# Production
DEPLOYMENT_ENV=production
```

**Option 2: FLASK_ENV (Flask convention)**
```bash
# Development
FLASK_ENV=development

# Production (disables test features)
FLASK_ENV=production
```

**Option 3: Production Indicators (Automatic)**
The system automatically detects production based on:
- DATABASE_URL pointing to cloud MySQL/PostgreSQL
- AWS_REGION, HEROKU_APP_NAME, GOOGLE_CLOUD_PROJECT, AZURE_SUBSCRIPTION_ID env vars

### Configuration Examples

**Local Development (SQLite):**
```bash
# No special env vars needed - defaults to LOCAL
# Or explicitly set:
DEPLOYMENT_ENV=local
```

**Development with MySQL:**
```bash
DEPLOYMENT_ENV=development
DATABASE_URL=mysql://user:pass@localhost:3306/voting_dev
```

**Production (AWS):**
```bash
DEPLOYMENT_ENV=production
DATABASE_URL=mysql://user:pass@prod-database.amazonaws.com/voting
AWS_REGION=us-east-1
# Test features automatically disabled
```

**Production (Heroku):**
```bash
DEPLOYMENT_ENV=production
DATABASE_URL=postgresql://user:pass@prod-db.example.com/voting
HEROKU_APP_NAME=voting-app-prod
# Test features automatically disabled
```

## Testing Strategy

### Test Data Credentials

The application seeds these test users during initialization:

| Role | Username | Password | Environment |
|------|----------|----------|-------------|
| Manager | admin | Admin@123456! | All |
| Delegate | delegate1 | Delegate@123! | All |
| Voter | voter1 | Password@123! | All |
| Voter | lix | Password@123! | All |
| Voter (test batch) | test_voter_* | TestVoter@Pass123 | Local/Dev only |

**Important:** The 100 test voters are only created when:
- `CREATE_TEST_VOTERS=true` is set, AND
- Environment detection confirms it's safe (Local/Development/Testing)

### Integration Testing

Integration tests run with these protections:

1. Environment detection in test fixtures (conftest.py)
2. Database isolation using Docker volumes
3. Fresh database initialization before each test run
4. No test data persists to production databases

```bash
# Run integration tests safely
python -m pytest tests/integration/ -v
```

## Monitoring & Logging

The environment detection system logs important events:

### Debug Logging (when enabled)
- Environment detection results
- Production indicator detection
- Test feature access requests

### Error Logging
- Production environment access to developer routes
- Production environment attempts to create test data
- Test feature access in staging environments

Example error log:
```
ERROR: Developer dashboard access attempt in PRODUCTION environment - BLOCKED
ERROR: Cannot enable test features in production environment
```

## Deployment Checklist

When deploying to production:

- [ ] Set `DEPLOYMENT_ENV=production` or equivalent production indicators
- [ ] Ensure DATABASE_URL points to production database
- [ ] Verify `is_safe_for_test_features()` returns False in production
- [ ] Check logs for any developer route access attempts
- [ ] Confirm no test users beyond the base 4 (admin, delegate1, voter1, lix)
- [ ] Verify login security checks are active (nonce validation, CAPTCHA)

## Troubleshooting

### Test Features Not Available in Local Environment

**Problem:** `is_safe_for_test_features()` returns False in local development.

**Solution:** Check environment detection:
```python
from app.environment import get_environment_detector
detector = get_environment_detector()
print(f"Environment: {detector.get_environment()}")
```

If not LOCAL/DEVELOPMENT, set:
```bash
DEPLOYMENT_ENV=local
```

### Production Environment Incorrectly Detected as Development

**Problem:** Test features are enabled when they shouldn't be.

**Solution:** Explicitly set production environment:
```bash
# WRONG - relies on detection:
AWS_REGION=us-east-1

# RIGHT - explicit and clear:
DEPLOYMENT_ENV=production
```

### Test Voters Not Being Created

**Problem:** 100 test voters not appearing in database.

**Causes:**
1. `CREATE_TEST_VOTERS` not set to `true`
2. Environment detected as production/staging
3. Test voter generator not available

**Solution:**
```bash
DEPLOYMENT_ENV=local
CREATE_TEST_VOTERS=true
python -c "from app import create_app; from app.init_db import init_database; app = create_app(); init_database(app)"
```

## Security Model

### Defense in Depth

The system uses multiple layers of protection:

1. **Environment Detection** - Multi-factor detection prevents false positives
2. **Explicit Safety Checks** - Each test feature site checks `is_safe_for_test_features()`
3. **Fail-Safe Defaults** - Production is the assumed default when uncertain
4. **Error Logging** - All access attempts to production features are logged
5. **Multiple Gates** - Even if one gate fails, others remain

### Production Safety Assertions

Critical test features include assertions to catch accidental usage:

```python
# In init_db.py (test voter creation)
if create_test_voters and TEST_VOTERS_AVAILABLE and is_safe_for_test_features():
    # is_safe_for_test_features() has already raised if production
    # This code cannot execute in production
    print("🧪 Creating test voters...")
```

## Future Enhancements

Potential improvements:

1. **Cloud Provider Detection** - Auto-detect AWS/Azure/GCP regions
2. **Container Detection** - Automatically detect Kubernetes/Docker environments
3. **Telemetry** - Track environment detection mismatches
4. **Audit Logging** - Comprehensive audit trail of test feature usage
5. **Admin Dashboard** - Real-time environment status view

## References

- [DEPLOYMENT GUIDE](./DEPLOYMENT.md) - Step-by-step deployment instructions
- [PASSWORD POLICY](./PASSWORD_POLICY.md) - Password security requirements
- [TEST VOTERS](./TEST_VOTERS.md) - Test data documentation

