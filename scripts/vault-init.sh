#!/bin/bash

# Vault initialization script for the voting system
# This script sets up the transit engine and creates the necessary keys for result signing

set -e

# Wait for Vault to be ready
echo "Waiting for Vault to be ready..."
until vault status > /dev/null 2>&1; do
    echo "Vault is not ready yet, waiting..."
    sleep 2
done

echo "Vault is ready!"

# Enable the transit secrets engine
echo "Enabling transit secrets engine..."
vault secrets enable -path=transit transit

# Create the results signing key
echo "Creating results signing key..."
vault write -f transit/keys/results-signing \
    type=rsa-2048 \
    allow_plaintext_backup=true

# Enable KV v2 secrets engine
echo "Enabling KV v2 secrets engine..."
vault secrets enable -path=kv kv-v2

# Create some sample secrets for the voting system
echo "Creating sample secrets..."

# JWT secret for Flask session management
vault kv put kv/app/jwt \
    secret="vault-managed-jwt-secret-key-for-tokens"

vault kv put kv/voting/config \
    admin_email="admin@voting-system.local" \
    system_name="Secure Voting System" \
    maintenance_mode="false"

vault kv put kv/voting/security \
    max_login_attempts="5" \
    session_timeout="3600" \
    password_min_length="12"

# Create a policy for the voting system
echo "Creating voting system policy..."
vault policy write voting-system - <<EOF
# Allow reading and writing to transit for result signing
path "transit/sign/results-signing" {
  capabilities = ["update"]
}

path "transit/verify/results-signing" {
  capabilities = ["update"]
}

# Allow reading JWT secret from KV
path "kv/data/app/jwt" {
  capabilities = ["read"]
}

# Allow reading configuration from KV
path "kv/data/voting/*" {
  capabilities = ["read"]
}

# Allow listing KV secrets
path "kv/metadata/app/jwt" {
  capabilities = ["read"]
}

path "kv/metadata/voting/*" {
  capabilities = ["list", "read"]
}
EOF

# Create a token for the voting system
echo "Creating voting system token..."
VAULT_TOKEN=$(vault token create -policy=voting-system -format=json | jq -r '.auth.client_token')

echo "Vault initialization complete!"
echo "=========================================="
echo "Vault Address: http://localhost:8200"
echo "Root Token: vault-dev-token"
echo "Voting System Token: $VAULT_TOKEN"
echo "=========================================="
echo ""
echo "You can access the Vault UI at: http://localhost:8200"
echo "Login with the root token: vault-dev-token"
echo ""
echo "The voting system will use the transit engine for result signing"
echo "and can access configuration from the KV store."
