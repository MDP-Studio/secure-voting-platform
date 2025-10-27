# Vault-Based Secrets Management Pattern

## Overview

This document outlines a comprehensive pattern for centralizing all secrets management using HashiCorp Vault, replacing scattered environment variables and hardcoded credentials with a secure, centralized approach.

## Current State vs Target State

### Current State (Scattered Secrets)
```
Environment Variables:
├── SECRET_KEY (Flask sessions)
├── DATABASE_URL (DB connection)
├── MAIL_USERNAME/PASSWORD (Email)
├── CLOUDFLARE_SECRET (Turnstile)
├── GEOIP_DB_PATH (Geo filtering)
└── Various API keys

Hardcoded Values:
├── Test user passwords
├── Default admin credentials
└── Development tokens
```

### Target State (Vault-Centralized)
```
Vault KV Store:
├── /voting/app/config
│   ├── flask_secret_key
│   ├── session_cookie_name
│   └── log_level
├── /voting/database/config
│   ├── connection_string
│   ├── username
│   └── password
├── /voting/email/config
│   ├── smtp_server
│   ├── username
│   ├── password
│   └── port
├── /voting/security/config
│   ├── cloudflare_secret
│   ├── geoip_db_path
│   └── max_login_attempts
└── /voting/external/apis
    ├── turnstile_secret
    └── monitoring_api_key
```

## Implementation Pattern

### 1. Vault Secrets Structure

```hcl
# Vault KV paths for different secret categories
/voting/app/config          # Application configuration
/voting/database/config     # Database credentials
/voting/email/config        # Email service credentials
/voting/security/config     # Security settings
/voting/external/apis       # External API keys
/voting/development/users   # Development user credentials
```

### 2. Enhanced Vault Client

```python
class EnhancedVaultClient:
    """Extended Vault client with configuration management patterns."""
    
    def get_app_config(self, key: str, default=None):
        """Get application configuration from Vault."""
        return self.kv_get('voting/app/config', key) or default
    
    def get_database_config(self):
        """Get complete database configuration."""
        return {
            'url': self.kv_get('voting/database/config', 'connection_string'),
            'username': self.kv_get('voting/database/config', 'username'),
            'password': self.kv_get('voting/database/config', 'password'),
        }
    
    def get_email_config(self):
        """Get complete email configuration."""
        return {
            'server': self.kv_get('voting/email/config', 'smtp_server'),
            'port': int(self.kv_get('voting/email/config', 'port') or 587),
            'username': self.kv_get('voting/email/config', 'username'),
            'password': self.kv_get('voting/email/config', 'password'),
            'use_tls': self.kv_get('voting/email/config', 'use_tls') == 'true',
        }
    
    def get_security_config(self, key: str, default=None):
        """Get security configuration from Vault."""
        return self.kv_get('voting/security/config', key) or default
    
    def get_external_api_key(self, service: str):
        """Get external API key for a service."""
        return self.kv_get('voting/external/apis', f'{service}_key')
```

### 3. Configuration Factory Pattern

```python
class VaultConfigFactory:
    """Factory for creating Flask configuration from Vault."""
    
    def __init__(self, vault_client: EnhancedVaultClient):
        self.vault = vault_client
    
    def create_flask_config(self) -> dict:
        """Create Flask configuration from Vault secrets."""
        config = {}
        
        # Application settings
        config['SECRET_KEY'] = self.vault.get_app_config('flask_secret_key', 'dev-secret')
        config['SESSION_COOKIE_NAME'] = self.vault.get_app_config('session_cookie_name', 'otp_session')
        config['LOG_LEVEL'] = self.vault.get_app_config('log_level', 'INFO')
        
        # Database configuration
        db_config = self.vault.get_database_config()
        if db_config['url']:
            config['SQLALCHEMY_DATABASE_URI'] = db_config['url']
        
        # Email configuration
        email_config = self.vault.get_email_config()
        if email_config['server']:
            config.update({
                'MAIL_SERVER': email_config['server'],
                'MAIL_PORT': email_config['port'],
                'MAIL_USE_TLS': email_config['use_tls'],
                'MAIL_USERNAME': email_config['username'],
                'MAIL_PASSWORD': email_config['password'],
            })
        
        # Security settings
        config['GEO_FILTER_ENABLED'] = self.vault.get_security_config('geo_filter_enabled', 'False').lower() == 'true'
        config['ENABLE_MFA'] = self.vault.get_security_config('enable_mfa', 'False').lower() == 'true'
        config['CLOUDFLARE_SECRET'] = self.vault.get_external_api_key('cloudflare')
        
        return config
```

### 4. Environment-Aware Secrets Loading

```python
class EnvironmentSecretsLoader:
    """Load secrets based on environment with fallback patterns."""
    
    def __init__(self, vault_client: EnhancedVaultClient, environment: str):
        self.vault = vault_client
        self.env = environment
    
    def load_secrets(self) -> dict:
        """Load secrets with environment-specific overrides."""
        secrets = {}
        
        # Base configuration
        secrets.update(self.vault.get_app_config())
        
        # Environment-specific overrides
        if self.env == 'production':
            secrets.update(self._load_production_secrets())
        elif self.env == 'staging':
            secrets.update(self._load_staging_secrets())
        else:
            secrets.update(self._load_development_secrets())
        
        return secrets
    
    def _load_production_secrets(self) -> dict:
        """Load production-specific secrets."""
        return {
            'SESSION_COOKIE_SECURE': True,
            'WTF_CSRF_ENABLED': True,
            'DEBUG': False,
        }
    
    def _load_development_secrets(self) -> dict:
        """Load development-specific secrets."""
        return {
            'SESSION_COOKIE_SECURE': False,
            'WTF_CSRF_ENABLED': False,
            'DEBUG': True,
        }
```

## Migration Strategy

### Phase 1: Core Application Secrets
1. **Flask Configuration**
   - Move `SECRET_KEY` to Vault
   - Centralize session configuration
   - Move logging configuration

2. **Database Credentials**
   - Store database connection strings in Vault
   - Implement connection pooling configuration
   - Add database health check secrets

### Phase 2: External Service Integration
1. **Email Service**
   - Move SMTP credentials to Vault
   - Store email templates and configuration
   - Add email service health monitoring

2. **Security Services**
   - Move CloudFlare Turnstile secrets
   - Store GeoIP database configuration
   - Centralize rate limiting configuration

### Phase 3: Development and Testing
1. **Test Data Management**
   - Store test user credentials in Vault
   - Implement test data seeding from Vault
   - Add test environment isolation

2. **API Keys and External Services**
   - Move all API keys to Vault
   - Implement key rotation policies
   - Add service-specific configurations

## Vault Policies

### Application Policy
```hcl
# Allow reading application configuration
path "kv/data/voting/app/config" {
  capabilities = ["read"]
}

# Allow reading database configuration
path "kv/data/voting/database/config" {
  capabilities = ["read"]
}

# Allow reading email configuration
path "kv/data/voting/email/config" {
  capabilities = ["read"]
}

# Allow reading security configuration
path "kv/data/voting/security/config" {
  capabilities = ["read"]
}

# Allow reading external API keys
path "kv/data/voting/external/apis" {
  capabilities = ["read"]
}

# Allow development user access in non-production
path "kv/data/voting/development/users" {
  capabilities = ["read"]
  condition = "not_production"
}
```

### Transit Engine Policy
```hcl
# Allow result signing
path "transit/sign/results-signing" {
  capabilities = ["update"]
}

# Allow signature verification
path "transit/verify/results-signing" {
  capabilities = ["update"]
}

# Allow key rotation (admin only)
path "transit/keys/results-signing/rotate" {
  capabilities = ["update"]
}
```

## Implementation Benefits

### 1. Security Improvements
- **Centralized Access Control**: All secrets managed through Vault policies
- **Audit Trail**: Complete logging of secret access
- **Key Rotation**: Automated rotation of sensitive credentials
- **Encryption at Rest**: All secrets encrypted in Vault

### 2. Operational Benefits
- **Environment Consistency**: Same secret structure across environments
- **Secret Discovery**: Easy to find and manage all secrets
- **Backup and Recovery**: Centralized backup of all secrets
- **Compliance**: Better compliance with security standards

### 3. Development Benefits
- **Local Development**: Easy secret management for developers
- **Testing**: Isolated test environments with separate secrets
- **Documentation**: Self-documenting secret structure
- **Debugging**: Better visibility into secret usage

## Migration Commands

### Initialize Vault with New Structure
```bash
# Create the new KV structure
vault kv put voting/app/config \
  flask_secret_key="$(openssl rand -base64 32)" \
  session_cookie_name="otp_session" \
  log_level="INFO"

vault kv put voting/database/config \
  connection_string="mysql+pymysql://user:pass@db:3306/votingdb" \
  username="votinguser" \
  password="votingpass"

vault kv put voting/email/config \
  smtp_server="smtp.gmail.com" \
  port="587" \
  username="your-email@gmail.com" \
  password="your-app-password" \
  use_tls="true"

vault kv put voting/security/config \
  geo_filter_enabled="True" \
  enable_mfa="False" \
  max_login_attempts="5" \
  lockout_duration="30"

vault kv put voting/external/apis \
  cloudflare_key="your-cloudflare-secret" \
  monitoring_api_key="your-monitoring-key"
```

### Update Application Code
```python
# Replace environment variable usage
# OLD:
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret')

# NEW:
vault_client = EnhancedVaultClient()
config_factory = VaultConfigFactory(vault_client)
config = config_factory.create_flask_config()
SECRET_KEY = config['SECRET_KEY']
```

## Monitoring and Alerting

### Secret Access Monitoring
```python
class VaultAuditLogger:
    """Log all Vault secret access for monitoring."""
    
    def log_secret_access(self, path: str, key: str, user: str):
        """Log secret access for audit purposes."""
        logging.info(f"Vault access: {user} accessed {path}:{key}")
        
        # Send to monitoring system
        self._send_to_monitoring({
            'event': 'vault_secret_access',
            'path': path,
            'key': key,
            'user': user,
            'timestamp': datetime.utcnow().isoformat()
        })
```

### Health Checks
```python
def vault_health_check():
    """Check Vault connectivity and secret availability."""
    try:
        vault_client = EnhancedVaultClient()
        
        # Test basic connectivity
        if not vault_client.is_enabled:
            return False, "Vault not enabled"
        
        # Test critical secrets
        critical_secrets = [
            'voting/app/config:flask_secret_key',
            'voting/database/config:connection_string',
        ]
        
        for secret_path in critical_secrets:
            path, key = secret_path.split(':')
            if not vault_client.kv_get(path, key):
                return False, f"Missing critical secret: {secret_path}"
        
        return True, "All secrets available"
    except Exception as e:
        return False, f"Vault health check failed: {e}"
```

This pattern provides a comprehensive, scalable approach to secrets management that will significantly improve your application's security posture while maintaining operational simplicity.
