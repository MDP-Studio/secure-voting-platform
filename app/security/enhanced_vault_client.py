"""
Enhanced Vault client with configuration management patterns.

This module extends the basic VaultClient with higher-level methods
for managing application configuration and secrets in a structured way.
"""

import os
import logging
from typing import Dict, Any, Optional, Union
from .vault_client import VaultClient


class EnhancedVaultClient(VaultClient):
    """
    Enhanced Vault client with configuration management patterns.
    
    Provides high-level methods for accessing different categories of secrets
    and configuration in a structured, environment-aware manner.
    """
    
    def __init__(self):
        super().__init__()
        self._config_cache = {}
        self._cache_ttl = 300  # 5 minutes cache TTL
    
    def get_app_config(self, key: str, default: Any = None) -> Any:
        """
        Get application configuration from Vault.
        
        Args:
            key: Configuration key to retrieve
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        return self.kv_get('voting/app/config', key) or default
    
    def get_database_config(self) -> Dict[str, str]:
        """
        Get complete database configuration from Vault.
        
        Returns:
            Dictionary containing database configuration
        """
        return {
            'url': self.kv_get('voting/database/config', 'connection_string'),
            'username': self.kv_get('voting/database/config', 'username'),
            'password': self.kv_get('voting/database/config', 'password'),
            'host': self.kv_get('voting/database/config', 'host'),
            'port': self.kv_get('voting/database/config', 'port'),
            'database': self.kv_get('voting/database/config', 'database'),
        }
    
    def get_email_config(self) -> Dict[str, Union[str, int, bool]]:
        """
        Get complete email configuration from Vault.
        
        Returns:
            Dictionary containing email configuration
        """
        port = self.kv_get('voting/email/config', 'port')
        use_tls = self.kv_get('voting/email/config', 'use_tls')
        
        return {
            'server': self.kv_get('voting/email/config', 'smtp_server'),
            'port': int(port) if port else 587,
            'username': self.kv_get('voting/email/config', 'username'),
            'password': self.kv_get('voting/email/config', 'password'),
            'use_tls': use_tls.lower() == 'true' if use_tls else True,
            'use_ssl': self.kv_get('voting/email/config', 'use_ssl', 'false').lower() == 'true',
            'default_sender': self.kv_get('voting/email/config', 'default_sender'),
        }
    
    def get_security_config(self, key: str, default: Any = None) -> Any:
        """
        Get security configuration from Vault.
        
        Args:
            key: Security configuration key
            default: Default value if key not found
            
        Returns:
            Security configuration value or default
        """
        return self.kv_get('voting/security/config', key) or default
    
    def get_external_api_key(self, service: str) -> Optional[str]:
        """
        Get external API key for a service.
        
        Args:
            service: Service name (e.g., 'cloudflare', 'monitoring')
            
        Returns:
            API key for the service or None
        """
        return self.kv_get('voting/external/apis', f'{service}_key')
    
    def get_development_user_credentials(self, username: str) -> Optional[Dict[str, str]]:
        """
        Get development user credentials from Vault.
        
        Args:
            username: Username to retrieve credentials for
            
        Returns:
            Dictionary with username and password or None
        """
        if not self.is_enabled:
            return None
            
        try:
            password = self.kv_get('voting/development/users', username)
            if password:
                return {
                    'username': username,
                    'password': password
                }
        except Exception as e:
            logging.warning(f"Failed to get development user credentials for {username}: {e}")
        
        return None
    
    def get_all_app_config(self) -> Dict[str, Any]:
        """
        Get all application configuration from Vault.
        
        Returns:
            Dictionary containing all application configuration
        """
        if not self.is_enabled:
            return {}
        
        try:
            # Try to get the entire config object
            resp = self._client.secrets.kv.v2.read_secret_version(
                path='voting/app/config',
                mount_point=self._kv_mount,
            )
            return resp['data']['data']
        except Exception as e:
            logging.warning(f"Failed to get all app config: {e}")
            return {}
    
    def set_app_config(self, key: str, value: str) -> bool:
        """
        Set application configuration in Vault.
        
        Args:
            key: Configuration key
            value: Configuration value
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_enabled:
            return False
        
        try:
            # Get existing config
            current_config = self.get_all_app_config()
            current_config[key] = value
            
            # Write back to Vault
            self._client.secrets.kv.v2.create_or_update_secret(
                path='voting/app/config',
                secret=current_config,
                mount_point=self._kv_mount,
            )
            return True
        except Exception as e:
            logging.error(f"Failed to set app config {key}: {e}")
            return False
    
    def get_environment_config(self, environment: str) -> Dict[str, Any]:
        """
        Get environment-specific configuration.
        
        Args:
            environment: Environment name (development, staging, production)
            
        Returns:
            Environment-specific configuration
        """
        base_config = self.get_all_app_config()
        env_config = self.kv_get(f'voting/environments/{environment}', 'config')
        
        if env_config:
            try:
                import json
                env_specific = json.loads(env_config)
                base_config.update(env_specific)
            except Exception as e:
                logging.warning(f"Failed to parse environment config for {environment}: {e}")
        
        return base_config
    
    def health_check(self) -> tuple[bool, str]:
        """
        Perform a health check on Vault connectivity and critical secrets.
        
        Returns:
            Tuple of (is_healthy, message)
        """
        try:
            if not self.is_enabled:
                return False, "Vault not enabled or not configured"
            
            # Test basic connectivity
            if not self._client.is_authenticated():
                return False, "Vault authentication failed"
            
            # Test critical secrets
            critical_secrets = [
                ('voting/app/config', 'flask_secret_key'),
                ('voting/database/config', 'connection_string'),
            ]
            
            for path, key in critical_secrets:
                if not self.kv_get(path, key):
                    return False, f"Missing critical secret: {path}:{key}"
            
            return True, "Vault health check passed"
        except Exception as e:
            return False, f"Vault health check failed: {e}"
    
    def rotate_secret(self, path: str, key: str) -> bool:
        """
        Rotate a secret in Vault (generate new value).
        
        Args:
            path: Vault path
            key: Secret key to rotate
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_enabled:
            return False
        
        try:
            # Generate new secret value
            import secrets
            import string
            
            if 'password' in key.lower():
                # Generate password
                new_value = ''.join(secrets.choice(
                    string.ascii_letters + string.digits + '!@#$%^&*'
                ) for _ in range(16))
            elif 'key' in key.lower():
                # Generate key
                new_value = secrets.token_urlsafe(32)
            else:
                # Generate generic secret
                new_value = secrets.token_urlsafe(24)
            
            # Get current secret data
            current_data = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self._kv_mount,
            )['data']['data']
            
            # Update with new value
            current_data[key] = new_value
            
            # Write back to Vault
            self._client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=current_data,
                mount_point=self._kv_mount,
            )
            
            logging.info(f"Rotated secret {path}:{key}")
            return True
        except Exception as e:
            logging.error(f"Failed to rotate secret {path}:{key}: {e}")
            return False


# Global instance
enhanced_vault_client = EnhancedVaultClient()
