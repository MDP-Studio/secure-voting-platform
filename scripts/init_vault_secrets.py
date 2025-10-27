#!/usr/bin/env python3
"""
Vault Secrets Initialization Script

This script initializes HashiCorp Vault with all the secrets and configuration
needed for the secure voting system. It creates the KV structure and populates
it with appropriate values for different environments.
"""

import os
import sys
import json
import secrets
import string
import argparse
import logging
from pathlib import Path

# Add the app directory to the path so we can import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import hvac
except ImportError:
    print("Error: hvac library not installed. Install with: pip install hvac")
    sys.exit(1)

from app.security.enhanced_vault_client import EnhancedVaultClient


class VaultSecretsInitializer:
    """Initialize Vault with all required secrets and configuration."""
    
    def __init__(self, vault_url: str = None, vault_token: str = None):
        self.vault_url = vault_url or os.environ.get('VAULT_ADDR', 'http://localhost:8200')
        self.vault_token = vault_token or os.environ.get('VAULT_TOKEN', 'vault-dev-token')
        self.client = hvac.Client(url=self.vault_url, token=self.vault_token)
        self.enhanced_client = EnhancedVaultClient()
        
        # Set up logging
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
    
    def initialize(self, environment: str = 'development', force: bool = False):
        """
        Initialize Vault with all secrets.
        
        Args:
            environment: Environment to initialize (development, staging, production)
            force: Force reinitialization even if secrets exist
        """
        self.logger.info(f"Initializing Vault secrets for {environment} environment")
        
        # Check Vault connectivity
        if not self.client.is_authenticated():
            self.logger.error("Vault authentication failed")
            return False
        
        # Enable KV secrets engine if not already enabled
        self._enable_kv_secrets_engine()
        
        # Initialize secrets
        success = True
        success &= self._init_app_config(environment, force)
        success &= self._init_database_config(environment, force)
        success &= self._init_email_config(environment, force)
        success &= self._init_security_config(environment, force)
        success &= self._init_external_api_config(environment, force)
        success &= self._init_development_users(environment, force)
        success &= self._init_environment_config(environment, force)
        
        if success:
            self.logger.info("Vault secrets initialization completed successfully")
        else:
            self.logger.error("Vault secrets initialization completed with errors")
        
        return success
    
    def _enable_kv_secrets_engine(self):
        """Enable KV secrets engine if not already enabled."""
        try:
            # Check if KV engine is already enabled
            mounts = self.client.sys.list_mounted_secrets_engines()
            if 'kv/' in mounts:
                self.logger.info("KV secrets engine already enabled")
                return
            
            # Enable KV engine
            self.client.sys.enable_secrets_engine(
                backend_type='kv',
                path='kv',
                options={'version': '2'}
            )
            self.logger.info("Enabled KV secrets engine")
        except Exception as e:
            self.logger.warning(f"Failed to enable KV engine (may already be enabled): {e}")
    
    def _init_app_config(self, environment: str, force: bool) -> bool:
        """Initialize application configuration."""
        try:
            path = 'voting/app/config'
            
            # Check if config already exists
            if not force and self._secret_exists(path):
                self.logger.info(f"App config already exists at {path}, skipping")
                return True
            
            config = {
                'flask_secret_key': self._generate_secret_key(),
                'session_cookie_name': 'otp_session',
                'log_level': 'INFO' if environment == 'production' else 'DEBUG',
                'debug': 'false' if environment == 'production' else 'true',
                'testing': 'false',
            }
            
            self.client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=config,
                mount_point='kv'
            )
            self.logger.info(f"Initialized app config at {path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize app config: {e}")
            return False
    
    def _init_database_config(self, environment: str, force: bool) -> bool:
        """Initialize database configuration."""
        try:
            path = 'voting/database/config'
            
            if not force and self._secret_exists(path):
                self.logger.info(f"Database config already exists at {path}, skipping")
                return True
            
            if environment == 'production':
                # Production database config (should be set manually)
                config = {
                    'connection_string': 'mysql+pymysql://user:pass@prod-db:3306/votingdb',
                    'username': 'votinguser',
                    'password': 'CHANGE_ME_IN_PRODUCTION',
                    'host': 'prod-db.example.com',
                    'port': '3306',
                    'database': 'votingdb',
                }
            else:
                # Development/staging database config
                config = {
                    'connection_string': 'mysql+pymysql://votinguser:votingpass@db:3306/votingdb',
                    'username': 'votinguser',
                    'password': 'votingpass',
                    'host': 'db',
                    'port': '3306',
                    'database': 'votingdb',
                }
            
            self.client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=config,
                mount_point='kv'
            )
            self.logger.info(f"Initialized database config at {path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize database config: {e}")
            return False
    
    def _init_email_config(self, environment: str, force: bool) -> bool:
        """Initialize email configuration."""
        try:
            path = 'voting/email/config'
            
            if not force and self._secret_exists(path):
                self.logger.info(f"Email config already exists at {path}, skipping")
                return True
            
            config = {
                'smtp_server': 'smtp.gmail.com',
                'port': '587',
                'username': 'your-email@gmail.com',
                'password': 'your-app-password',
                'use_tls': 'true',
                'use_ssl': 'false',
                'default_sender': 'your-email@gmail.com',
            }
            
            self.client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=config,
                mount_point='kv'
            )
            self.logger.info(f"Initialized email config at {path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize email config: {e}")
            return False
    
    def _init_security_config(self, environment: str, force: bool) -> bool:
        """Initialize security configuration."""
        try:
            path = 'voting/security/config'
            
            if not force and self._secret_exists(path):
                self.logger.info(f"Security config already exists at {path}, skipping")
                return True
            
            config = {
                'geo_filter_enabled': 'true' if environment != 'development' else 'false',
                'enable_mfa': 'false',  # Disabled by default
                'max_login_attempts': '5',
                'lockout_duration': '30',
                'password_expiry_days': '90',
                'geoip_db_path': '/data/GeoLite2-Country.mmdb',
                'session_timeout': '3600',  # 1 hour
                'password_min_length': '12',
                'require_special_chars': 'true',
            }
            
            self.client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=config,
                mount_point='kv'
            )
            self.logger.info(f"Initialized security config at {path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize security config: {e}")
            return False
    
    def _init_external_api_config(self, environment: str, force: bool) -> bool:
        """Initialize external API configuration."""
        try:
            path = 'voting/external/apis'
            
            if not force and self._secret_exists(path):
                self.logger.info(f"External API config already exists at {path}, skipping")
                return True
            
            config = {
                'cloudflare_key': 'your-cloudflare-secret-key',
                'monitoring_api_key': 'your-monitoring-api-key',
                'analytics_key': 'your-analytics-key',
            }
            
            self.client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=config,
                mount_point='kv'
            )
            self.logger.info(f"Initialized external API config at {path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize external API config: {e}")
            return False
    
    def _init_development_users(self, environment: str, force: bool) -> bool:
        """Initialize development user credentials."""
        try:
            path = 'voting/development/users'
            
            if not force and self._secret_exists(path):
                self.logger.info(f"Development users already exist at {path}, skipping")
                return True
            
            # Only create development users for non-production environments
            if environment == 'production':
                self.logger.info("Skipping development users for production environment")
                return True
            
            users = {
                'admin': 'Admin@123456!',
                'delegate1': 'Delegate@123!',
                'voter1': 'Password@123!',
                'lix': 'Password@123!',
            }
            
            self.client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=users,
                mount_point='kv'
            )
            self.logger.info(f"Initialized development users at {path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize development users: {e}")
            return False
    
    def _init_environment_config(self, environment: str, force: bool) -> bool:
        """Initialize environment-specific configuration."""
        try:
            path = f'voting/environments/{environment}'
            
            if not force and self._secret_exists(path):
                self.logger.info(f"Environment config already exists at {path}, skipping")
                return True
            
            if environment == 'production':
                config = {
                    'config': json.dumps({
                        'SESSION_COOKIE_SECURE': True,
                        'WTF_CSRF_ENABLED': True,
                        'DEBUG': False,
                        'TESTING': False,
                    })
                }
            elif environment == 'staging':
                config = {
                    'config': json.dumps({
                        'SESSION_COOKIE_SECURE': True,
                        'WTF_CSRF_ENABLED': True,
                        'DEBUG': False,
                        'TESTING': False,
                    })
                }
            else:  # development
                config = {
                    'config': json.dumps({
                        'SESSION_COOKIE_SECURE': False,
                        'WTF_CSRF_ENABLED': False,
                        'DEBUG': True,
                        'TESTING': False,
                    })
                }
            
            self.client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=config,
                mount_point='kv'
            )
            self.logger.info(f"Initialized {environment} environment config at {path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize environment config: {e}")
            return False
    
    def _secret_exists(self, path: str) -> bool:
        """Check if a secret already exists."""
        try:
            self.client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point='kv'
            )
            return True
        except Exception:
            return False
    
    def _generate_secret_key(self) -> str:
        """Generate a secure secret key."""
        return secrets.token_urlsafe(32)
    
    def _generate_password(self, length: int = 16) -> str:
        """Generate a secure password."""
        chars = string.ascii_letters + string.digits + '!@#$%^&*'
        return ''.join(secrets.choice(chars) for _ in range(length))
    
    def list_secrets(self):
        """List all secrets in the voting namespace."""
        try:
            # List all paths under voting/
            resp = self.client.secrets.kv.v2.list_secrets(
                path='voting',
                mount_point='kv'
            )
            
            print("Vault secrets structure:")
            self._print_secrets_tree(resp.get('data', {}).get('keys', []), 'voting/')
        except Exception as e:
            self.logger.error(f"Failed to list secrets: {e}")
    
    def _print_secrets_tree(self, keys: list, prefix: str = ''):
        """Print secrets in a tree structure."""
        for key in sorted(keys):
            if key.endswith('/'):
                print(f"{prefix}{key}")
                # This is a directory, we'd need to recurse
                # For now, just show the structure
            else:
                print(f"{prefix}{key}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Initialize Vault secrets')
    parser.add_argument('--environment', '-e', 
                       choices=['development', 'staging', 'production'],
                       default='development',
                       help='Environment to initialize')
    parser.add_argument('--vault-url', 
                       default=os.environ.get('VAULT_ADDR', 'http://localhost:8200'),
                       help='Vault URL')
    parser.add_argument('--vault-token',
                       default=os.environ.get('VAULT_TOKEN', 'vault-dev-token'),
                       help='Vault token')
    parser.add_argument('--force', '-f',
                       action='store_true',
                       help='Force reinitialization even if secrets exist')
    parser.add_argument('--list', '-l',
                       action='store_true',
                       help='List existing secrets')
    
    args = parser.parse_args()
    
    initializer = VaultSecretsInitializer(args.vault_url, args.vault_token)
    
    if args.list:
        initializer.list_secrets()
    else:
        success = initializer.initialize(args.environment, args.force)
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
