"""
Environment detection and configuration management.

This module provides safe environment detection to ensure test/development
features are only enabled in appropriate environments (local/dev), never in
production.

Environment Detection Hierarchy:
1. FLASK_ENV environment variable (production/development/testing)
2. DEPLOYMENT_ENV environment variable (local/development/staging/production)
3. DATABASE_URL (hints at deployment type)
4. TESTING flag in app.config

Test/Development Features:
- Disabled login security checks (nonce, CAPTCHA)
- Test data seeding in database
- Debug dashboards and information endpoints
- Relaxed password policies
- Enhanced error messages
"""

import os
import logging
from typing import Literal
from enum import Enum

logger = logging.getLogger(__name__)


class Environment(Enum):
    """Enumeration of supported deployment environments."""
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"
    LOCAL = "local"
    TESTING = "testing"


class EnvironmentDetector:
    """
    Detects and manages current deployment environment with safety checks.
    
    This detector ensures that test/development features are only enabled
    in truly safe environments (local/development), never in production
    or staging.
    """

    # Patterns that indicate production-like environments
    PRODUCTION_INDICATORS = {
        'DATABASE_URL',  # RDS, hosted database
        'HEROKU_APP_NAME',
        'AWS_REGION',
        'GOOGLE_CLOUD_PROJECT',
        'AZURE_SUBSCRIPTION_ID',
    }

    def __init__(self):
        """Initialize environment detector."""
        self._env = self._detect_environment()
        self._is_safe_for_testing = self._check_safe_for_testing()

    def _detect_environment(self) -> Environment:
        """
        Detect current environment from multiple sources.
        
        Detection order (highest priority first):
        1. DEPLOYMENT_ENV variable (explicit override)
        2. FLASK_ENV variable (Flask convention)
        3. Heuristics from environment variables
        4. Default to LOCAL (safest assumption)
        """
        # Priority 1: Explicit DEPLOYMENT_ENV
        deployment_env = os.environ.get('DEPLOYMENT_ENV', '').lower().strip()
        if deployment_env:
            try:
                return Environment(deployment_env)
            except ValueError:
                logger.warning(f"Invalid DEPLOYMENT_ENV: {deployment_env}, auto-detecting instead")

        # Priority 2: FLASK_ENV
        flask_env = os.environ.get('FLASK_ENV', '').lower().strip()
        if flask_env == 'production':
            return Environment.PRODUCTION
        elif flask_env == 'development':
            return Environment.DEVELOPMENT
        elif flask_env == 'testing':
            return Environment.TESTING

        # Priority 3: Heuristics - check for production indicators
        if self._has_production_indicators():
            logger.info("Production indicators detected in environment variables")
            return Environment.PRODUCTION

        # Priority 4: Default to LOCAL (safest for development)
        logger.info("No explicit environment set, defaulting to LOCAL")
        return Environment.LOCAL

    def _has_production_indicators(self) -> bool:
        """Check if environment variables suggest production deployment."""
        for indicator in self.PRODUCTION_INDICATORS:
            if indicator in os.environ:
                logger.debug(f"Production indicator found: {indicator}")
                return True
        return False

    def _check_safe_for_testing(self) -> bool:
        """
        Verify that test features should be enabled.
        
        Test features are only safe in:
        - LOCAL environment
        - DEVELOPMENT environment
        - TESTING environment
        
        Never enable in PRODUCTION or STAGING.
        """
        safe_envs = {Environment.LOCAL, Environment.DEVELOPMENT, Environment.TESTING}
        is_safe = self._env in safe_envs
        
        if not is_safe:
            logger.warning(
                f"Test features DISABLED: environment is {self._env.value}, "
                f"which is not a safe testing environment"
            )
        
        return is_safe

    @property
    def current(self) -> Environment:
        """Get current environment."""
        return self._env

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self._env == Environment.PRODUCTION

    @property
    def is_staging(self) -> bool:
        """Check if running in staging."""
        return self._env == Environment.STAGING

    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self._env == Environment.DEVELOPMENT

    @property
    def is_local(self) -> bool:
        """Check if running locally."""
        return self._env == Environment.LOCAL

    @property
    def is_testing(self) -> bool:
        """Check if running in test mode."""
        return self._env == Environment.TESTING

    @property
    def safe_for_test_features(self) -> bool:
        """Check if test/development features should be enabled."""
        return self._is_safe_for_testing

    def require_safe_environment(self, feature_name: str = "This feature") -> bool:
        """
        Check if it's safe to enable a feature, with logging.
        
        Args:
            feature_name: Description of feature requiring safe environment
            
        Returns:
            True if safe, False if not safe
            
        Raises:
            RuntimeError: If feature is attempted to be enabled in production
        """
        if self.is_production:
            raise RuntimeError(
                f"{feature_name} cannot be enabled in production environment. "
                f"Current environment: {self._env.value}"
            )
        
        if not self._is_safe_for_testing:
            logger.warning(
                f"{feature_name} requested but current environment "
                f"({self._env.value}) is not marked as safe for testing"
            )
            return False
        
        return True

    def log_configuration(self):
        """Log current environment configuration for debugging."""
        logger.info(f"🌍 Environment: {self._env.value}")
        logger.info(f"   Safe for test features: {self._is_safe_for_testing}")
        logger.info(f"   Is production: {self.is_production}")
        logger.info(f"   Is staging: {self.is_staging}")
        logger.info(f"   Is development: {self.is_development}")
        logger.info(f"   Is local: {self.is_local}")
        logger.info(f"   Is testing: {self.is_testing}")


# Global instance
_detector: EnvironmentDetector | None = None


def get_environment_detector() -> EnvironmentDetector:
    """Get or create global environment detector instance."""
    global _detector
    if _detector is None:
        _detector = EnvironmentDetector()
        _detector.log_configuration()
    return _detector


def is_safe_for_test_features() -> bool:
    """Check if test/development features should be enabled."""
    return get_environment_detector().safe_for_test_features


def is_production() -> bool:
    """Check if running in production."""
    return get_environment_detector().is_production


def get_current_environment() -> Environment:
    """Get current environment."""
    return get_environment_detector().current
