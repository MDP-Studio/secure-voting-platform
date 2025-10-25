"""
Configuration factory for creating Flask configuration from Vault secrets.

This module provides a factory pattern for creating application configuration
from Vault secrets with environment-aware overrides and fallback patterns.
"""

import os
import logging
from typing import Dict, Any, Optional
from .enhanced_vault_client import EnhancedVaultClient
from .environment import EnvironmentDetector, Environment


class VaultConfigFactory:
    """
    Factory for creating Flask configuration from Vault secrets.
    
    Provides environment-aware configuration loading with fallback patterns
    and structured secret management.
    """
    
    def __init__(self, vault_client: Optional[EnhancedVaultClient] = None):
        self.vault = vault_client or EnhancedVaultClient()
        self.environment_detector = EnvironmentDetector()
        self._config_cache = {}
    
    def create_flask_config(self, environment: Optional[str] = None) -> Dict[str, Any]:
        """
        Create Flask configuration from Vault secrets.
        
        Args:
            environment: Override environment detection
            
        Returns:
            Dictionary containing Flask configuration
        """
        env = environment or self.environment_detector.detect_environment()
        cache_key = f"flask_config_{env}"
        
        # Check cache first
        if cache_key in self._config_cache:
            return self._config_cache[cache_key]
        
        config = {}
        
        # Load base configuration
        config.update(self._load_base_config())
        
        # Load environment-specific configuration
        config.update(self._load_environment_config(env))
        
        # Load secrets from Vault
        config.update(self._load_vault_secrets(env))
        
        # Apply final overrides
        config.update(self._load_environment_overrides(env))
        
        # Cache the configuration
        self._config_cache[cache_key] = config
        
        return config
    
    def _load_base_config(self) -> Dict[str, Any]:
        """Load base Flask configuration."""
        return {
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
            'WTF_CSRF_ENABLED': True,
            'SESSION_COOKIE_SAMESITE': 'Lax',
        }
    
    def _load_environment_config(self, environment: str) -> Dict[str, Any]:
        """Load environment-specific configuration."""
        if environment == Environment.PRODUCTION:
            return {
                'DEBUG': False,
                'TESTING': False,
                'SESSION_COOKIE_SECURE': True,
                'WTF_CSRF_ENABLED': True,
            }
        elif environment == Environment.STAGING:
            return {
                'DEBUG': False,
                'TESTING': False,
                'SESSION_COOKIE_SECURE': True,
                'WTF_CSRF_ENABLED': True,
            }
        elif environment == Environment.TESTING:
            return {
                'DEBUG': False,
                'TESTING': True,
                'SESSION_COOKIE_SECURE': False,
                'WTF_CSRF_ENABLED': False,
            }
        else:  # Development/Local
            return {
                'DEBUG': True,
                'TESTING': False,
                'SESSION_COOKIE_SECURE': False,
                'WTF_CSRF_ENABLED': False,
            }
    
    def _load_vault_secrets(self, environment: str) -> Dict[str, Any]:
        """Load secrets from Vault."""
        config = {}
        
        if not self.vault.is_enabled:
            logging.warning("Vault not enabled, using environment variables as fallback")
            return self._load_environment_fallback()
        
        try:
            # Application configuration
            config.update(self._load_app_secrets())
            
            # Database configuration
            config.update(self._load_database_secrets())
            
            # Email configuration
            config.update(self._load_email_secrets())
            
            # Security configuration
            config.update(self._load_security_secrets())
            
            # External API configuration
            config.update(self._load_external_api_secrets())
            
        except Exception as e:
            logging.error(f"Failed to load Vault secrets: {e}")
            # Fallback to environment variables
            config.update(self._load_environment_fallback())
        
        return config
    
    def _load_app_secrets(self) -> Dict[str, Any]:
        """Load application secrets from Vault."""
        return {
            'SECRET_KEY': self.vault.get_app_config('flask_secret_key', 'dev-secret'),
            'SESSION_COOKIE_NAME': self.vault.get_app_config('session_cookie_name', 'otp_session'),
            'LOG_LEVEL': self.vault.get_app_config('log_level', 'INFO'),
        }
    
    def _load_database_secrets(self) -> Dict[str, Any]:
        """Load database secrets from Vault."""
        db_config = self.vault.get_database_config()
        
        if db_config['url']:
            return {
                'SQLALCHEMY_DATABASE_URI': db_config['url'],
            }
        elif db_config['host'] and db_config['database']:
            # Construct connection string from components
            username = db_config['username'] or 'root'
            password = db_config['password'] or ''
            host = db_config['host']
            port = db_config['port'] or '3306'
            database = db_config['database']
            
            connection_string = f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}"
            return {
                'SQLALCHEMY_DATABASE_URI': connection_string,
            }
        
        return {}
    
    def _load_email_secrets(self) -> Dict[str, Any]:
        """Load email secrets from Vault."""
        email_config = self.vault.get_email_config()
        
        if not email_config['server']:
            return {}
        
        config = {
            'MAIL_SERVER': email_config['server'],
            'MAIL_PORT': email_config['port'],
            'MAIL_USE_TLS': email_config['use_tls'],
            'MAIL_USE_SSL': email_config['use_ssl'],
        }
        
        if email_config['username']:
            config['MAIL_USERNAME'] = email_config['username']
        if email_config['password']:
            config['MAIL_PASSWORD'] = email_config['password']
        if email_config['default_sender']:
            config['MAIL_DEFAULT_SENDER'] = email_config['default_sender']
        
        return config
    
    def _load_security_secrets(self) -> Dict[str, Any]:
        """Load security secrets from Vault."""
        return {
            'GEO_FILTER_ENABLED': self.vault.get_security_config('geo_filter_enabled', 'False').lower() == 'true',
            'ENABLE_MFA': self.vault.get_security_config('enable_mfa', 'False').lower() == 'true',
            'MAX_LOGIN_ATTEMPTS': int(self.vault.get_security_config('max_login_attempts', '5')),
            'LOCKOUT_DURATION': int(self.vault.get_security_config('lockout_duration', '30')),
            'PASSWORD_EXPIRY_DAYS': int(self.vault.get_security_config('password_expiry_days', '90')),
        }
    
    def _load_external_api_secrets(self) -> Dict[str, Any]:
        """Load external API secrets from Vault."""
        config = {}
        
        # CloudFlare Turnstile
        cloudflare_secret = self.vault.get_external_api_key('cloudflare')
        if cloudflare_secret:
            config['CLOUDFLARE_SECRET'] = cloudflare_secret
        
        # Monitoring API
        monitoring_key = self.vault.get_external_api_key('monitoring')
        if monitoring_key:
            config['MONITORING_API_KEY'] = monitoring_key
        
        # GeoIP configuration
        geoip_path = self.vault.get_security_config('geoip_db_path')
        if geoip_path:
            config['GEOIP_DB_PATH'] = geoip_path
        
        return config
    
    def _load_environment_fallback(self) -> Dict[str, Any]:
        """Load configuration from environment variables as fallback."""
        return {
            'SECRET_KEY': os.environ.get('SECRET_KEY', 'dev-secret'),
            'SQLALCHEMY_DATABASE_URI': os.environ.get('DATABASE_URL'),
            'MAIL_SERVER': os.environ.get('MAIL_SERVER', 'smtp.gmail.com'),
            'MAIL_PORT': int(os.environ.get('MAIL_PORT', '587')),
            'MAIL_USE_TLS': os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true',
            'MAIL_USERNAME': os.environ.get('MAIL_USERNAME'),
            'MAIL_PASSWORD': os.environ.get('MAIL_PASSWORD'),
            'GEO_FILTER_ENABLED': os.environ.get('GEO_FILTER_ENABLED', 'False').lower() == 'true',
            'ENABLE_MFA': os.environ.get('ENABLE_MFA', 'False').lower() == 'true',
            'CLOUDFLARE_SECRET': os.environ.get('CLOUDFLARE_SECRET'),
            'GEOIP_DB_PATH': os.environ.get('GEOIP_DB_PATH'),
        }
    
    def _load_environment_overrides(self, environment: str) -> Dict[str, Any]:
        """Load final environment-specific overrides."""
        overrides = {}
        
        if environment == Environment.PRODUCTION:
            overrides.update({
                'SESSION_COOKIE_SECURE': True,
                'WTF_CSRF_ENABLED': True,
                'DEBUG': False,
            })
        elif environment == Environment.TESTING:
            overrides.update({
                'WTF_CSRF_ENABLED': False,
                'TESTING': True,
            })
        
        return overrides
    
    def get_development_user_credentials(self) -> Dict[str, Dict[str, str]]:
        """
        Get development user credentials from Vault.
        
        Returns:
            Dictionary mapping usernames to credentials
        """
        if not self.vault.is_enabled:
            return self._get_default_test_credentials()
        
        try:
            # Get all development users
            resp = self.vault._client.secrets.kv.v2.list_secrets(
                path='voting/development/users',
                mount_point=self.vault._kv_mount,
            )
            
            users = {}
            for username in resp.get('data', {}).get('keys', []):
                creds = self.vault.get_development_user_credentials(username)
                if creds:
                    users[username] = creds
            
            return users
        except Exception as e:
            logging.warning(f"Failed to get development user credentials: {e}")
            return self._get_default_test_credentials()
    
    def _get_default_test_credentials(self) -> Dict[str, Dict[str, str]]:
        """Get default test credentials as fallback."""
        return {
            'admin': {'username': 'admin', 'password': 'Admin@123456!'},
            'delegate1': {'username': 'delegate1', 'password': 'Delegate@123!'},
            'voter1': {'username': 'voter1', 'password': 'Password@123!'},
            'lix': {'username': 'lix', 'password': 'Password@123!'},
        }
    
    def clear_cache(self):
        """Clear the configuration cache."""
        self._config_cache.clear()
    
    def reload_config(self, environment: Optional[str] = None) -> Dict[str, Any]:
        """
        Reload configuration from Vault.
        
        Args:
            environment: Override environment detection
            
        Returns:
            Fresh configuration dictionary
        """
        self.clear_cache()
        return self.create_flask_config(environment)


# Global factory instance
config_factory = VaultConfigFactory()
