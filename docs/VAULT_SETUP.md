# HashiCorp Vault Integration

This document describes the HashiCorp Vault integration for the secure voting system, which provides enhanced security for result signing and configuration management.

## Overview

The voting system now integrates with HashiCorp Vault to provide:

- **Result Signing**: Uses Vault's Transit engine for cryptographic signing of election results
- **Key Management**: Centralized and secure key storage and rotation
- **Configuration Management**: Secure storage of sensitive configuration values
- **Audit Trail**: Comprehensive logging of all cryptographic operations

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Voting Web    │    │   HashiCorp     │    │   MySQL DB      │
│   Application   │◄──►│     Vault       │    │                 │
│                 │    │                 │    │                 │
│ - Result Signing│    │ - Transit Engine│    │ - Vote Storage  │
│ - Configuration │    │ - KV Store      │    │ - User Data     │
│ - Authentication│    │ - Policies      │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Quick Start

### 1. Start the System

```bash
# Start all services including Vault
docker-compose up -d

# Check that all services are running
docker-compose ps
```

### 2. Initialize Vault

```bash
# Option 1: Use the Python script (recommended)
python3 scripts/init_vault.py

# Option 2: Use the shell script
docker-compose exec vault /vault-init.sh
```

### 3. Verify Integration

```bash
# Check Vault status
curl http://localhost:8200/v1/sys/health

# Access Vault UI
open http://localhost:8200
# Login with token: vault-dev-token
```

## Vault Configuration

### Environment Variables

The web application is configured with the following Vault environment variables:

```yaml
VAULT_ADDR: "http://vault:8200"          # Vault server URL
VAULT_TOKEN: "vault-dev-token"           # Authentication token
VAULT_MOUNT: "transit"                   # Transit engine mount point
VAULT_KV_MOUNT: "kv"                     # KV store mount point
VAULT_TRANSIT_KEY: "results-signing"     # Transit key name
```

### Secrets Engines

#### Transit Engine (`/transit`)

Used for cryptographic operations:

- **Key**: `results-signing` (RSA-2048)
- **Purpose**: Sign and verify election results
- **Operations**: 
  - `transit/sign/results-signing` - Sign data
  - `transit/verify/results-signing` - Verify signatures

#### KV Store (`/kv`)

Used for configuration management:

- **Path**: `voting/config` - System configuration
- **Path**: `voting/security` - Security settings
- **Path**: `voting/keys/` - Migrated RSA keys (if any)

## Usage Examples

### Result Signing

The application automatically uses Vault for result signing when available:

```python
from app.security.signing_service import sign_data, verify_signature

# Sign election results
results_data = b'{"candidate1": 100, "candidate2": 150}'
signature = sign_data(results_data)

# Verify signature
is_valid = verify_signature(results_data, signature)
```

### Configuration Access

Access configuration from Vault:

```python
from app.security.vault_client import vault_client

# Get configuration values
admin_email = vault_client.kv_get('voting/config', 'admin_email')
max_attempts = vault_client.kv_get('voting/security', 'max_login_attempts')
```

## Security Features

### 1. Key Management

- **Centralized Storage**: All cryptographic keys stored in Vault
- **Key Rotation**: Easy rotation of signing keys
- **Access Control**: Fine-grained policies for key access
- **Audit Logging**: All key operations are logged

### 2. Policy-Based Access

The voting system uses a dedicated policy:

```hcl
# Allow result signing
path "transit/sign/results-signing" {
  capabilities = ["update"]
}

# Allow signature verification
path "transit/verify/results-signing" {
  capabilities = ["update"]
}

# Allow configuration reading
path "kv/data/voting/*" {
  capabilities = ["read"]
}
```

### 3. Fallback Security

If Vault is unavailable, the system falls back to local RSA keys:

- Local keys are loaded from the instance folder
- Same cryptographic strength (RSA-2048)
- Seamless operation without Vault dependency

## Development vs Production

### Development Setup

The current configuration uses Vault in development mode:

- **Token**: `vault-dev-token` (hardcoded for convenience)
- **Storage**: In-memory (data lost on restart)
- **UI Access**: Available at http://localhost:8200

### Production Considerations

For production deployment:

1. **Enable Vault UI**: Configure proper TLS certificates
2. **Persistent Storage**: Use file or Consul backend
3. **Token Management**: Use proper token lifecycle management
4. **High Availability**: Deploy Vault cluster
5. **Backup Strategy**: Regular backup of Vault data
6. **Network Security**: Restrict Vault access to application only

## Monitoring and Troubleshooting

### Health Checks

```bash
# Check Vault health
curl http://localhost:8200/v1/sys/health

# Check application logs
docker-compose logs web | grep -i vault

# Check Vault logs
docker-compose logs vault
```

### Common Issues

1. **Vault Not Ready**: Wait for Vault to initialize (usually 10-30 seconds)
2. **Authentication Failed**: Verify VAULT_TOKEN environment variable
3. **Key Not Found**: Run the initialization script
4. **Network Issues**: Ensure containers are on the same network

### Debugging

Enable debug logging:

```bash
# Set debug level in docker-compose.yml
LOG_LEVEL: debug
```

## Migration from Local Keys

If you have existing RSA keys in the instance folder:

```bash
# The init script will automatically migrate them
python3 scripts/init_vault.py --instance-path ./instance

# Or manually migrate
docker-compose exec web python3 -c "
from app.security.vault_client import vault_client
# Migration code here
"
```

## API Reference

### VaultClient Methods

```python
# Check if Vault is enabled
vault_client.is_enabled

# Sign data using transit engine
signature = vault_client.transit_sign('results-signing', data)

# Verify signature
is_valid = vault_client.transit_verify('results-signing', data, signature)

# Get configuration value
value = vault_client.kv_get('voting/config', 'admin_email')
```

## Security Best Practices

1. **Token Security**: Never commit tokens to version control
2. **Network Isolation**: Use private networks for Vault communication
3. **Regular Rotation**: Rotate tokens and keys regularly
4. **Audit Monitoring**: Monitor Vault audit logs
5. **Backup Strategy**: Regular backup of Vault data and policies
6. **Access Control**: Use least-privilege principles for policies

## Troubleshooting Commands

```bash
# Restart Vault
docker-compose restart vault

# Reinitialize Vault
docker-compose exec vault vault operator init

# Check Vault status
docker-compose exec vault vault status

# List secrets engines
docker-compose exec vault vault secrets list

# Test authentication
docker-compose exec vault vault auth -method=token token=vault-dev-token
```

## Support

For issues related to Vault integration:

1. Check the application logs: `docker-compose logs web`
2. Check Vault logs: `docker-compose logs vault`
3. Verify Vault health: `curl http://localhost:8200/v1/sys/health`
4. Review this documentation
5. Check the Vault UI at http://localhost:8200
