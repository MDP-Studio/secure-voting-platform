"""
Vault-based configuration module for Flask application.

This module provides Vault-integrated configuration loading for the Flask application,
replacing scattered environment variables with centralized secrets management.
"""

import os
import logging
from typing import Dict, Any, Optional
from .security.config_factory import VaultConfigFactory
from .security.enhanced_vault_client import EnhancedVaultClient
from .environment import EnvironmentDetector


class VaultFlaskConfig:
    """
    Vault-based Flask configuration loader.
    
    This class provides a clean interface for loading Flask configuration
    from Vault secrets with environment-aware overrides and fallback patterns.
    """
    
    def __init__(self):
        self.vault_client = EnhancedVaultClient()
        self.config_factory = VaultConfigFactory(self.vault_client)
        self.environment_detector = EnvironmentDetector()
        self._config = None
        self._environment = None
    
    def load_config(self, environment: Optional[str] = None) -> Dict[str, Any]:
        """
        Load Flask configuration from Vault.
        
        Args:
            environment: Override environment detection
            
        Returns:
            Dictionary containing Flask configuration
        """
        self._environment = environment or self.environment_detector.detect_environment()
        self._config = self.config_factory.create_flask_config(self._environment)
        
        # Log configuration source
        if self.vault_client.is_enabled:
            logging.info("Configuration loaded from Vault")
        else:
            logging.warning("Vault not available, using environment variables as fallback")
        
        return self._config
    
    def get_config(self) -> Dict[str, Any]:
        """Get the loaded configuration."""
        if self._config is None:
            self.load_config()
        return self._config
    
    def get_secret(self, category: str, key: str, default: Any = None) -> Any:
        """
        Get a specific secret from Vault.
        
        Args:
            category: Secret category (app, database, email, security, external)
            key: Secret key
            default: Default value if not found
            
        Returns:
            Secret value or default
        """
        if not self.vault_client.is_enabled:
            return default
        
        try:
            if category == 'app':
                return self.vault_client.get_app_config(key, default)
            elif category == 'database':
                db_config = self.vault_client.get_database_config()
                return db_config.get(key, default)
            elif category == 'email':
                email_config = self.vault_client.get_email_config()
                return email_config.get(key, default)
            elif category == 'security':
                return self.vault_client.get_security_config(key, default)
            elif category == 'external':
                return self.vault_client.get_external_api_key(key)
            else:
                logging.warning(f"Unknown secret category: {category}")
                return default
        except Exception as e:
            logging.error(f"Failed to get secret {category}:{key}: {e}")
            return default
    
    def health_check(self) -> tuple[bool, str]:
        """
        Perform a health check on Vault connectivity and critical secrets.
        
        Returns:
            Tuple of (is_healthy, message)
        """
        return self.vault_client.health_check()
    
    def reload_config(self) -> Dict[str, Any]:
        """Reload configuration from Vault."""
        self._config = None
        return self.load_config()
    
    def get_development_credentials(self) -> Dict[str, Dict[str, str]]:
        """Get development user credentials."""
        return self.config_factory.get_development_user_credentials()
    
    def is_vault_enabled(self) -> bool:
        """Check if Vault is enabled and available."""
        return self.vault_client.is_enabled


# Global configuration instance
vault_config = VaultFlaskConfig()


def create_vault_config() -> Dict[str, Any]:
    """
    Create Flask configuration using Vault.
    
    This function can be used as a drop-in replacement for the existing
    configuration loading in app/__init__.py
    
    Returns:
        Dictionary containing Flask configuration
    """
    return vault_config.load_config()


def get_vault_secret(category: str, key: str, default: Any = None) -> Any:
    """
    Get a secret from Vault by category and key.
    
    Args:
        category: Secret category (app, database, email, security, external)
        key: Secret key
        default: Default value if not found
        
    Returns:
        Secret value or default
    """
    return vault_config.get_secret(category, key, default)


def vault_health_check() -> tuple[bool, str]:
    """
    Check Vault health and critical secrets availability.
    
    Returns:
        Tuple of (is_healthy, message)
    """
    return vault_config.health_check()


# Backward compatibility functions
def get_secret_key() -> str:
    """Get Flask secret key from Vault or environment."""
    return get_vault_secret('app', 'flask_secret_key', os.environ.get('SECRET_KEY', 'dev-secret'))


def get_database_url() -> Optional[str]:
    """Get database URL from Vault or environment."""
    return get_vault_secret('database', 'url') or os.environ.get('DATABASE_URL')


def get_mail_config() -> Dict[str, Any]:
    """Get email configuration from Vault or environment."""
    if vault_config.is_vault_enabled():
        return vault_config.get_secret('email', 'all', {})
    else:
        return {
            'MAIL_SERVER': os.environ.get('MAIL_SERVER', 'smtp.gmail.com'),
            'MAIL_PORT': int(os.environ.get('MAIL_PORT', '587')),
            'MAIL_USE_TLS': os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true',
            'MAIL_USERNAME': os.environ.get('MAIL_USERNAME'),
            'MAIL_PASSWORD': os.environ.get('MAIL_PASSWORD'),
        }


def get_security_config() -> Dict[str, Any]:
    """Get security configuration from Vault or environment."""
    if vault_config.is_vault_enabled():
        return {
            'GEO_FILTER_ENABLED': get_vault_secret('security', 'geo_filter_enabled', 'False').lower() == 'true',
            'ENABLE_MFA': get_vault_secret('security', 'enable_mfa', 'False').lower() == 'true',
            'MAX_LOGIN_ATTEMPTS': int(get_vault_secret('security', 'max_login_attempts', '5')),
            'LOCKOUT_DURATION': int(get_vault_secret('security', 'lockout_duration', '30')),
        }
    else:
        return {
            'GEO_FILTER_ENABLED': os.environ.get('GEO_FILTER_ENABLED', 'False').lower() == 'true',
            'ENABLE_MFA': os.environ.get('ENABLE_MFA', 'False').lower() == 'true',
            'MAX_LOGIN_ATTEMPTS': 5,
            'LOCKOUT_DURATION': 30,
        }
