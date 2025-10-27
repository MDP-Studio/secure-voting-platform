"""
Tests for anti-robot login blocking.

Verifies that the auth.py login handler blocks non-browser requests
when TESTING mode is disabled (i.e., in production-like environments).
"""

import pytest
from itsdangerous import URLSafeTimedSerializer


@pytest.fixture
def app_with_security(app):
    """Create app with TESTING=False to enable security checks."""
    with app.app_context():
        app.config['TESTING'] = False
        yield app


@pytest.fixture
def client_with_security(app_with_security):
    """Test client with security checks enabled."""
    return app_with_security.test_client()


class TestLoginNonceRequirement:
    """Tests that verify login requires a valid nonce."""

    def test_login_blocked_without_nonce(self, app_with_security, client_with_security):
        """Login POST without nonce should be blocked."""
        response = client_with_security.post(
            '/login',
            data={
                'username': 'voter1',
                'password': 'Password@123!',
                # No login_nonce field
            }
        )
        
        assert response.status_code == 200
        assert b'Human verification required' in response.data
    
    def test_login_blocked_with_invalid_nonce(self, app_with_security, client_with_security):
        """Login POST with invalid nonce should be blocked."""
        response = client_with_security.post(
            '/login',
            data={
                'username': 'voter1',
                'password': 'Password@123!',
                'login_nonce': 'invalid-nonce-xyz',
            }
        )
        
        assert response.status_code == 200
        assert b'Human verification failed' in response.data
    
    def test_login_succeeds_with_valid_nonce(self, app_with_security, client_with_security):
        """Login POST with valid nonce should proceed (may fail on other checks)."""
        with app_with_security.app_context():
            # Generate valid nonce
            s = URLSafeTimedSerializer(app_with_security.config['SECRET_KEY'], salt='login-nonce')
            valid_nonce = s.dumps('test-nonce-data')
        
        response = client_with_security.post(
            '/login',
            data={
                'username': 'voter1',
                'password': 'Password@123!',
                'login_nonce': valid_nonce,
            },
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'http://localhost/login',  # Required since Turnstile not configured
            }
        )
        
        # Should NOT fail on nonce check; may fail elsewhere (MFA, password, etc.)
        # The fact that we passed nonce means we didn't see "Human verification" error
        assert b'Human verification required' not in response.data


class TestLoginCliBlocking:
    """Tests that verify CLI/HTTP-library User-Agent is blocked."""

    @pytest.mark.parametrize("cli_ua", [
        'curl/7.64.1',
        'wget/1.20.3',
        'httpie/3.1.0',
        'python-requests/2.28.0',
        'httpx/0.23.0',
        'powershell/7.0',
    ])
    def test_cli_user_agent_blocked(self, app_with_security, client_with_security, cli_ua):
        """CLI User-Agent should be blocked at nonce check stage."""
        with app_with_security.app_context():
            s = URLSafeTimedSerializer(app_with_security.config['SECRET_KEY'], salt='login-nonce')
            valid_nonce = s.dumps('test-nonce-data')
        
        response = client_with_security.post(
            '/login',
            data={
                'username': 'voter1',
                'password': 'Password@123!',
                'login_nonce': valid_nonce,
            },
            headers={'User-Agent': cli_ua}
        )
        
        assert response.status_code == 200
        # Should see browser requirement message
        assert b'web browser' in response.data or b'command-line' in response.data.lower()
    
    def test_browser_user_agent_allowed(self, app_with_security, client_with_security):
        """Browser User-Agent should NOT be blocked on UA check."""
        with app_with_security.app_context():
            s = URLSafeTimedSerializer(app_with_security.config['SECRET_KEY'], salt='login-nonce')
            valid_nonce = s.dumps('test-nonce-data')
        
        response = client_with_security.post(
            '/login',
            data={
                'username': 'voter1',
                'password': 'Password@123!',
                'login_nonce': valid_nonce,
            },
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        
        # Should NOT be rejected on User-Agent grounds
        assert b'command-line' not in response.data.lower()


class TestLoginGotchaHoneypot:
    """Tests that verify the GOTCHA honeypot field blocks bots."""

    def test_gotcha_field_filled_blocks_login(self, client_with_security):
        """Filling the hidden gotcha field should block login immediately."""
        response = client_with_security.post(
            '/login',
            data={
                'username': 'voter1',
                'password': 'Password@123!',
                'gotcha': 'filled-by-bot',  # Hidden field - bots often fill it
            }
        )
        
        assert response.status_code == 200
        assert b'Bot-like activity detected' in response.data
    
    def test_empty_gotcha_allowed(self, client_with_security):
        """Empty gotcha field should NOT trigger honeypot block."""
        response = client_with_security.post(
            '/login',
            data={
                'username': 'voter1',
                'password': 'Password@123!',
                'gotcha': '',  # Empty is correct (human behavior)
            }
        )
        
        # Should NOT be rejected for gotcha
        assert b'Bot-like activity detected' not in response.data
    
    def test_missing_gotcha_allowed(self, client_with_security):
        """Missing gotcha field should NOT trigger honeypot block."""
        response = client_with_security.post(
            '/login',
            data={
                'username': 'voter1',
                'password': 'Password@123!',
                # No gotcha field at all
            }
        )
        
        # Should NOT be rejected for gotcha
        assert b'Bot-like activity detected' not in response.data


class TestLoginOriginRefererCheck:
    """Tests that verify Origin/Referer header requirement (when no Turnstile)."""

    def test_login_blocked_without_origin_or_referer(self, app_with_security, client_with_security):
        """POST without Origin or Referer should be blocked (when no Turnstile configured)."""
        with app_with_security.app_context():
            s = URLSafeTimedSerializer(app_with_security.config['SECRET_KEY'], salt='login-nonce')
            valid_nonce = s.dumps('test-nonce-data')
        
        # Use browser UA (to pass UA check) but omit Origin/Referer
        response = client_with_security.post(
            '/login',
            data={
                'username': 'voter1',
                'password': 'Password@123!',
                'login_nonce': valid_nonce,
            },
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                # Explicitly set empty Origin/Referer (test client may not auto-add them)
            },
            environ_base={
                'HTTP_ORIGIN': '',
                'HTTP_REFERER': '',
            }
        )
        
        assert response.status_code == 200
        assert b'Human verification required' in response.data
    
    def test_login_allowed_with_referer(self, app_with_security, client_with_security):
        """POST with Referer header should pass Origin/Referer check."""
        with app_with_security.app_context():
            s = URLSafeTimedSerializer(app_with_security.config['SECRET_KEY'], salt='login-nonce')
            valid_nonce = s.dumps('test-nonce-data')
        
        response = client_with_security.post(
            '/login',
            data={
                'username': 'voter1',
                'password': 'Password@123!',
                'login_nonce': valid_nonce,
            },
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'http://localhost/login',
            }
        )
        
        # Should pass Origin/Referer check (may fail on user lookup, password, etc.)
        # Key: should NOT be blocked for missing Origin/Referer
        assert b'Human verification required' not in response.data or b'failed' not in response.data.lower()
