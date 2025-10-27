#!/usr/bin/env python3
"""
Vault initialization script for the voting system.
This script sets up Vault with the necessary engines and keys for result signing.
"""

import os
import sys
import time
import json
import base64
from pathlib import Path

# Add the app directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

try:
    import hvac
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError as e:
    print(f"Error: Missing required dependencies: {e}")
    print("Please install hvac and cryptography: pip install hvac cryptography")
    sys.exit(1)


class VaultInitializer:
    def __init__(self, vault_url="http://localhost:8200", token="vault-dev-token"):
        self.vault_url = vault_url
        self.token = token
        self.client = hvac.Client(url=vault_url, token=token)
        
    def wait_for_vault(self, max_retries=30):
        """Wait for Vault to be ready and authenticated."""
        print("Waiting for Vault to be ready...")
        for i in range(max_retries):
            try:
                if self.client.is_authenticated():
                    print("Vault is ready and authenticated!")
                    return True
            except Exception as e:
                print(f"Vault not ready yet (attempt {i+1}/{max_retries}): {e}")
                time.sleep(2)
        return False
    
    def enable_transit_engine(self):
        """Enable the transit secrets engine."""
        print("Enabling transit secrets engine...")
        try:
            self.client.sys.enable_secrets_engine(
                backend_type='transit',
                path='transit'
            )
            print("✓ Transit engine enabled")
        except hvac.exceptions.InvalidRequest as e:
            if "path is already in use" in str(e):
                print("✓ Transit engine already enabled")
            else:
                raise
    
    def create_signing_key(self):
        """Create the results signing key in transit."""
        print("Creating results signing key...")
        try:
            self.client.secrets.transit.create_key(
                name='results-signing',
                key_type='rsa-2048',
                allow_plaintext_backup=True
            )
            print("✓ Results signing key created")
        except hvac.exceptions.InvalidRequest as e:
            if "key already exists" in str(e):
                print("✓ Results signing key already exists")
            else:
                raise
    
    def enable_kv_engine(self):
        """Enable the KV v2 secrets engine."""
        print("Enabling KV v2 secrets engine...")
        try:
            self.client.sys.enable_secrets_engine(
                backend_type='kv-v2',
                path='kv'
            )
            print("✓ KV v2 engine enabled")
        except hvac.exceptions.InvalidRequest as e:
            if "path is already in use" in str(e):
                print("✓ KV v2 engine already enabled")
            else:
                raise
    
    def create_sample_secrets(self):
        """Create sample configuration secrets."""
        print("Creating sample secrets...")
        
        # JWT secret for Flask session management (used by jwt_helpers.py)
        self.client.secrets.kv.v2.create_or_update_secret(
            path='app/jwt',
            secret={
                'secret': 'vault-managed-jwt-secret-key-for-tokens'
            },
            mount_point='kv'
        )
        print("  - JWT secret created")
        
        # Voting system configuration
        self.client.secrets.kv.v2.create_or_update_secret(
            path='voting/config',
            secret={
                'admin_email': 'admin@voting-system.local',
                'system_name': 'Secure Voting System',
                'maintenance_mode': 'false',
                'vault_integration': 'enabled'
            },
            mount_point='kv'
        )
        print("  - Voting config created")
        
        # Security configuration
        self.client.secrets.kv.v2.create_or_update_secret(
            path='voting/security',
            secret={
                'max_login_attempts': '5',
                'session_timeout': '3600',
                'password_min_length': '12',
                'rate_limit_enabled': 'true'
            },
            mount_point='kv'
        )
        print("  - Security config created")
        
        print("✓ Sample secrets created")
    
    def create_voting_policy(self):
        """Create a policy for the voting system."""
        print("Creating voting system policy...")
        
        policy = """
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
"""
        
        self.client.sys.create_or_update_policy(
            name='voting-system',
            policy=policy
        )
        print("✓ Voting system policy created")
    
    def create_voting_token(self):
        """Create a token for the voting system."""
        print("Creating voting system token...")
        
        token_response = self.client.auth.token.create(
            policies=['voting-system'],
            ttl='24h',
            renewable=True
        )
        
        voting_token = token_response['auth']['client_token']
        print(f"✓ Voting system token created: {voting_token[:20]}...")
        return voting_token
    
    def migrate_existing_keys(self, instance_path):
        """Migrate existing RSA keys to Vault (if they exist)."""
        instance_path = Path(instance_path)
        private_key_path = instance_path / "private_key.pem"
        public_key_path = instance_path / "public_key.pem"
        
        if not (private_key_path.exists() and public_key_path.exists()):
            print("No existing keys found to migrate")
            return
        
        print("Found existing keys, migrating to Vault...")
        
        try:
            # Read the existing private key
            with open(private_key_path, 'rb') as f:
                private_key = serialization.load_pem_private_key(f.read(), password=None)
            
            # Export the private key in PEM format
            private_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            
            # Store the private key in Vault's KV store
            self.client.secrets.kv.v2.create_or_update_secret(
                path='voting/keys/private_key',
                secret={'key': private_pem.decode('utf-8')},
                mount_point='kv'
            )
            
            # Read and store the public key
            with open(public_key_path, 'rb') as f:
                public_key = serialization.load_pem_public_key(f.read())
            
            public_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            
            self.client.secrets.kv.v2.create_or_update_secret(
                path='voting/keys/public_key',
                secret={'key': public_pem.decode('utf-8')},
                mount_point='kv'
            )
            
            print("✓ Existing keys migrated to Vault")
            
        except Exception as e:
            print(f"Warning: Could not migrate existing keys: {e}")
    
    def initialize(self, instance_path=None):
        """Initialize Vault with all necessary components."""
        print("Initializing Vault for the voting system...")
        print("=" * 50)
        
        if not self.wait_for_vault():
            print("Error: Could not connect to Vault")
            return False
        
        try:
            self.enable_transit_engine()
            self.create_signing_key()
            self.enable_kv_engine()
            self.create_sample_secrets()
            self.create_voting_policy()
            voting_token = self.create_voting_token()
            
            if instance_path:
                self.migrate_existing_keys(instance_path)
            
            print("\n" + "=" * 50)
            print("Vault initialization complete!")
            print("=" * 50)
            print(f"Vault URL: {self.vault_url}")
            print(f"Root Token: {self.token}")
            print(f"Voting Token: {voting_token}")
            print("\nYou can access the Vault UI at: http://localhost:8200")
            print("Login with the root token to explore the configuration.")
            print("\nThe voting system will use Vault for:")
            print("- Result signing via transit engine")
            print("- Configuration management via KV store")
            print("- Secure key management")
            
            return True
            
        except Exception as e:
            print(f"Error during initialization: {e}")
            return False


def main():
    """Main function to run the Vault initialization."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Initialize Vault for the voting system')
    parser.add_argument('--vault-url', default='http://localhost:8200',
                       help='Vault URL (default: http://localhost:8200)')
    parser.add_argument('--token', default='vault-dev-token',
                       help='Vault root token (default: vault-dev-token)')
    parser.add_argument('--instance-path', 
                       help='Path to instance folder with existing keys to migrate')
    
    args = parser.parse_args()
    
    initializer = VaultInitializer(args.vault_url, args.token)
    success = initializer.initialize(args.instance_path)
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
