# Vault Migration Guide

This guide walks through migrating the secure voting system from environment variables to HashiCorp Vault for centralized secrets management.

## Overview

The migration involves:
1. Setting up Vault with the new secrets structure
2. Updating the Flask application to use Vault-based configuration
3. Migrating existing secrets to Vault
4. Testing the new configuration system

## Step 1: Initialize Vault Secrets

### Run the Vault Secrets Initialization Script

```bash
# Initialize Vault with development secrets
python scripts/init_vault_secrets.py --environment development

# For production (requires manual secret updates)
python scripts/init_vault_secrets.py --environment production --force
```

### Verify Secrets Structure

```bash
# List all secrets
python scripts/init_vault_secrets.py --list

# Check Vault UI
open http://localhost:8200
# Login with token: vault-dev-token
```

## Step 2: Update Flask Application

### Option A: Gradual Migration (Recommended)

Update `app/__init__.py` to use Vault configuration with fallback:

```python
# Add at the top of app/__init__.py
from .vault_config import create_vault_config, vault_health_check

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True, template_folder='templates')
    
    # Load configuration from Vault with fallback
    vault_config = create_vault_config()
    
    # Merge Vault config with existing config
    app.config.from_mapping(vault_config)
    
    # Keep existing config as fallback
    app.config.from_mapping(
        # ... existing configuration ...
    )
    
    # Add Vault health check endpoint
    @app.route('/vault-health')
    def vault_health():
        is_healthy, message = vault_health_check()
        return {'status': 'healthy' if is_healthy else 'unhealthy', 'message': message}
    
    # ... rest of the function ...
```

### Option B: Complete Migration

Replace the entire configuration section in `app/__init__.py`:

```python
def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True, template_folder='templates')
    
    # Load all configuration from Vault
    vault_config = create_vault_config()
    app.config.from_mapping(vault_config)
    
    # Apply test configuration if provided
    if test_config:
        app.config.update(test_config)
    
    # ... rest of the function ...
```

## Step 3: Update Secret Usage Throughout the Application

### Database Configuration

**Before:**
```python
SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or ('sqlite:///' + os.path.join(app.instance_path, 'app.db'))
```

**After:**
```python
from .vault_config import get_database_url

SQLALCHEMY_DATABASE_URI = get_database_url() or ('sqlite:///' + os.path.join(app.instance_path, 'app.db'))
```

### Email Configuration

**Before:**
```python
MAIL_SERVER=os.environ.get('MAIL_SERVER', 'smtp.gmail.com'),
MAIL_PORT=int(os.environ.get('MAIL_PORT', 587)),
MAIL_USERNAME=os.environ.get('MAIL_USERNAME'),
MAIL_PASSWORD=os.environ.get('MAIL_PASSWORD'),
```

**After:**
```python
from .vault_config import get_mail_config

mail_config = get_mail_config()
MAIL_SERVER=mail_config.get('MAIL_SERVER', 'smtp.gmail.com'),
MAIL_PORT=mail_config.get('MAIL_PORT', 587),
MAIL_USERNAME=mail_config.get('MAIL_USERNAME'),
MAIL_PASSWORD=mail_config.get('MAIL_PASSWORD'),
```

### Security Configuration

**Before:**
```python
GEO_FILTER_ENABLED=os.environ.get('GEO_FILTER_ENABLED', 'False').lower() in ('true', '1', 'yes'),
ENABLE_MFA=os.environ.get('ENABLE_MFA', 'False').lower() in ('true', '1', 'yes'),
```

**After:**
```python
from .vault_config import get_security_config

security_config = get_security_config()
GEO_FILTER_ENABLED=security_config.get('GEO_FILTER_ENABLED', False),
ENABLE_MFA=security_config.get('ENABLE_MFA', False),
```

## Step 4: Update Docker Configuration

### Update docker-compose.yml

Add Vault environment variables to the web service:

```yaml
web:
  # ... existing configuration ...
  environment:
    # Vault configuration
    VAULT_ADDR: "http://vault:8200"
    VAULT_TOKEN: "vault-dev-token"
    VAULT_MOUNT: "transit"
    VAULT_KV_MOUNT: "kv"
    VAULT_TRANSIT_KEY: "results-signing"
    
    # Keep existing environment variables as fallback
    DATABASE_URL: mysql+pymysql://votinguser:votingpass@db:3306/votingdb
    SECRET_KEY: "fallback-secret-key"
    # ... other existing variables ...
```

### Update CI/CD Workflows

Update `.github/workflows/tests.yml` to include Vault configuration:

```yaml
- name: Set up environment variables (SQLite for testing)
  run: |
    echo "DEPLOYMENT_ENV=testing" >> $GITHUB_ENV
    echo "FLASK_ENV=testing" >> $GITHUB_ENV
    echo "SECRET_KEY=test-secret-key-do-not-use-in-production" >> $GITHUB_ENV
    echo "GEO_FILTER_ENABLED=False" >> $GITHUB_ENV
    echo "ENABLE_MFA=False" >> $GITHUB_ENV
    # Vault configuration for testing
    echo "VAULT_ADDR=http://localhost:8200" >> $GITHUB_ENV
    echo "VAULT_TOKEN=vault-dev-token" >> $GITHUB_ENV
```

## Step 5: Update Development and Testing

### Update Test Configuration

Update `tests/conftest.py` to use Vault configuration:

```python
from app.vault_config import create_vault_config

@pytest.fixture
def app():
    """Create and configure a test app instance."""
    # Load Vault configuration for testing
    vault_config = create_vault_config()
    
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        **vault_config  # Merge Vault configuration
    })
    
    # ... rest of the function ...
```

### Update Development Scripts

Update `run_demo.py` to use Vault configuration:

```python
from app.vault_config import create_vault_config

def main():
    # Load configuration from Vault
    vault_config = create_vault_config()
    
    # Create Flask app with Vault configuration
    app = create_app()
    
    # ... rest of the function ...
```

## Step 6: Production Deployment

### Set Production Secrets

For production deployment, manually set the production secrets in Vault:

```bash
# Set production database credentials
vault kv put voting/database/config \
  connection_string="mysql+pymysql://prod-user:secure-password@prod-db:3306/votingdb" \
  username="prod-user" \
  password="secure-password"

# Set production email credentials
vault kv put voting/email/config \
  smtp_server="smtp.your-provider.com" \
  username="noreply@yourdomain.com" \
  password="your-email-password"

# Set production security settings
vault kv put voting/security/config \
  geo_filter_enabled="true" \
  enable_mfa="true" \
  max_login_attempts="3" \
  lockout_duration="60"
```

### Update Production Environment Variables

Set only the essential Vault connection variables:

```bash
# Production environment variables
export VAULT_ADDR="https://vault.yourdomain.com"
export VAULT_TOKEN="your-production-token"
export VAULT_MOUNT="transit"
export VAULT_KV_MOUNT="kv"
export DEPLOYMENT_ENV="production"
```

## Step 7: Monitoring and Maintenance

### Add Vault Health Monitoring

Add Vault health checks to your monitoring:

```python
# In your health check endpoint
@app.route('/health')
def health():
    # Check Vault health
    vault_healthy, vault_message = vault_health_check()
    
    return {
        'status': 'healthy' if vault_healthy else 'unhealthy',
        'vault': {
            'status': 'healthy' if vault_healthy else 'unhealthy',
            'message': vault_message
        },
        'database': check_database_health(),
        'timestamp': datetime.utcnow().isoformat()
    }
```

### Set Up Secret Rotation

Implement secret rotation for critical secrets:

```python
# Rotate secrets periodically
def rotate_secrets():
    vault_client = EnhancedVaultClient()
    
    # Rotate database password
    vault_client.rotate_secret('voting/database/config', 'password')
    
    # Rotate email password
    vault_client.rotate_secret('voting/email/config', 'password')
    
    # Rotate Flask secret key
    vault_client.rotate_secret('voting/app/config', 'flask_secret_key')
```

## Step 8: Testing the Migration

### Test Vault Integration

```bash
# Test Vault connectivity
python -c "from app.vault_config import vault_health_check; print(vault_health_check())"

# Test configuration loading
python -c "from app.vault_config import create_vault_config; print(create_vault_config())"

# Test secret retrieval
python -c "from app.vault_config import get_vault_secret; print(get_vault_secret('app', 'flask_secret_key'))"
```

### Run Full Test Suite

```bash
# Run all tests to ensure Vault integration works
python -m pytest tests/ -v

# Run specific Vault-related tests
python -m pytest tests/test_vault_integration.py -v
```

## Rollback Plan

If issues arise, you can quickly rollback by:

1. **Revert code changes** to use environment variables
2. **Set environment variables** with the same values as Vault
3. **Disable Vault** by removing VAULT_ADDR and VAULT_TOKEN

```bash
# Quick rollback - set environment variables
export SECRET_KEY="your-secret-key"
export DATABASE_URL="mysql+pymysql://user:pass@db:3306/votingdb"
export MAIL_USERNAME="your-email@gmail.com"
export MAIL_PASSWORD="your-password"
# ... other variables ...

# Remove Vault environment variables
unset VAULT_ADDR
unset VAULT_TOKEN
```

## Benefits After Migration

### Security Improvements
- ✅ **Centralized Access Control**: All secrets managed through Vault policies
- ✅ **Audit Trail**: Complete logging of secret access
- ✅ **Key Rotation**: Automated rotation of sensitive credentials
- ✅ **Encryption at Rest**: All secrets encrypted in Vault

### Operational Benefits
- ✅ **Environment Consistency**: Same secret structure across environments
- ✅ **Secret Discovery**: Easy to find and manage all secrets
- ✅ **Backup and Recovery**: Centralized backup of all secrets
- ✅ **Compliance**: Better compliance with security standards

### Development Benefits
- ✅ **Local Development**: Easy secret management for developers
- ✅ **Testing**: Isolated test environments with separate secrets
- ✅ **Documentation**: Self-documenting secret structure
- ✅ **Debugging**: Better visibility into secret usage

## Troubleshooting

### Common Issues

1. **Vault Not Available**: Application falls back to environment variables
2. **Authentication Failed**: Check VAULT_TOKEN environment variable
3. **Secret Not Found**: Verify secret path and key in Vault
4. **Permission Denied**: Check Vault policies for the token

### Debug Commands

```bash
# Check Vault status
curl http://localhost:8200/v1/sys/health

# List secrets
vault kv list kv/voting

# Read specific secret
vault kv get kv/voting/app/config

# Test authentication
vault auth -method=token token=vault-dev-token
```

This migration provides a robust, scalable approach to secrets management that significantly improves your application's security posture while maintaining operational simplicity.
