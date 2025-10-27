#!/usr/bin/env python3
"""
Quick Vault initialization for Docker containers.
This runs once when the app starts to ensure Vault secrets are set up.
"""

import os
import sys
import time
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def initialize_vault_secrets():
    """Initialize required Vault secrets if they don't exist."""
    
    vault_addr = os.environ.get('VAULT_ADDR', 'http://vault:8200')
    vault_token = os.environ.get('VAULT_TOKEN', 'vault-dev-token')
    kv_mount = os.environ.get('VAULT_KV_MOUNT', 'kv')
    
    if not vault_addr or not vault_token:
        logger.info("Vault not configured, skipping initialization")
        return True
    
    try:
        import hvac
    except ImportError:
        logger.warning("hvac not installed, skipping Vault initialization")
        return True
    
    # Wait for Vault to be ready
    max_retries = 30
    for attempt in range(max_retries):
        try:
            client = hvac.Client(url=vault_addr, token=vault_token)
            if client.is_authenticated():
                logger.info("✓ Connected to Vault")
                break
            logger.info(f"Waiting for Vault to be ready... (attempt {attempt + 1}/{max_retries})")
            time.sleep(2)
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to connect to Vault after {max_retries} attempts: {e}")
                return False
            logger.debug(f"Vault connection attempt {attempt + 1} failed: {e}")
            time.sleep(2)
            continue
    
    try:
        # Check if JWT secret exists
        try:
            resp = client.secrets.kv.v2.read_secret_version(
                path='app/jwt',
                mount_point=kv_mount,
            )
            logger.info("✓ JWT secret already exists in Vault")
        except hvac.exceptions.InvalidPath:
            # Secret doesn't exist, create it
            logger.info("Creating JWT secret in Vault...")
            client.secrets.kv.v2.create_or_update_secret(
                path='app/jwt',
                secret={'secret': 'vault-managed-jwt-secret-key-for-tokens'},
                mount_point=kv_mount
            )
            logger.info("✓ JWT secret created")
        
        # Check if transit engine exists
        try:
            engines = client.sys.list_mounted_secrets_engines()
            if 'transit/' not in engines['data']:
                logger.info("Enabling transit engine...")
                client.sys.enable_secrets_engine(
                    backend_type='transit',
                    path='transit'
                )
                logger.info("✓ Transit engine enabled")
                
                # Create signing key
                logger.info("Creating results signing key...")
                client.secrets.transit.create_key(
                    name='results-signing',
                    key_type='rsa-2048',
                    allow_plaintext_backup=True
                )
                logger.info("✓ Results signing key created")
            else:
                logger.info("✓ Transit engine already enabled")
        except Exception as e:
            logger.warning(f"Could not verify transit engine: {e}")
        
        logger.info("✓ Vault initialization complete")
        return True
        
    except Exception as e:
        logger.error(f"Vault initialization failed: {e}")
        return False


if __name__ == '__main__':
    success = initialize_vault_secrets()
    sys.exit(0 if success else 1)
