"""
Integration Tests for Voting System

These tests run against running Docker containers to verify:
- Application health and availability
- Authentication flows
- API functionality

Run with: pytest tests/integration/ -v
Run against Docker: pytest tests/integration/ -v --base-url=http://localhost
"""

import pytest
import time


class TestHealthChecks:
    """Test application health and availability."""

    def test_app_health_check(self, http_runner):
        """Test basic application health check."""
        health = http_runner.health_check()

        assert health['status'] == 'healthy', f"App unhealthy: {health.get('error')}"
        assert health['response_time'] < 5.0, f"Response too slow: {health['response_time']}s"
        assert health['status_code'] == 200

    def test_home_page_accessible(self, http_runner):
        """Test home page is accessible."""
        response = http_runner.get('/')

        assert response.status_code in [200, 302], f"Unexpected status: {response.status_code}"
        # Should redirect to login if not authenticated
        if response.status_code == 302:
            assert 'login' in response.headers.get('Location', '').lower()

    def test_static_assets_accessible(self, http_runner):
        """Test static assets are served correctly."""
        # Test favicon
        response = http_runner.get('/static/favicon.ico')
        assert response.status_code == 200, "Favicon not accessible"

        # Test logo
        response = http_runner.get('/static/logo.svg')
        assert response.status_code == 200, "Logo not accessible"


class TestAuthentication:
    """Test authentication flows and security."""

    def test_login_page_loads(self, http_runner):
        """Test login page loads correctly."""
        response = http_runner.get('/login')

        assert response.status_code == 200
        assert 'login' in response.text.lower()
        assert 'username' in response.text.lower()
        assert 'password' in response.text.lower()

    def test_successful_admin_login(self, clean_session):
        """Test successful admin login."""
        success = clean_session.login('admin', 'admin123')
        assert success, "Admin login failed"

        # Verify authenticated
        assert clean_session.is_authenticated(), "Not authenticated after login"

    def test_successful_voter_login(self, clean_session):
        """Test successful voter login."""
        success = clean_session.login('voter1', 'password123')
        assert success, "Voter login failed"

        assert clean_session.is_authenticated(), "Not authenticated after login"

    def test_failed_login_attempts(self, clean_session):
        """Test failed login attempts."""
        # Wrong password
        success = clean_session.login('admin', 'wrongpassword')
        assert not success, "Login should fail with wrong password"

        # Wrong username
        success = clean_session.login('nonexistent', 'password123')
        assert not success, "Login should fail with wrong username"

    def test_logout_functionality(self, clean_session):
        """Test logout functionality."""
        # Login first
        clean_session.login('admin', 'admin123')
        assert clean_session.is_authenticated(), "Should be authenticated"

        # Logout
        clean_session.logout()

        # Verify logged out
        assert not clean_session.is_authenticated(), "Should be logged out"


class TestAPIFunctionality:
    """Test core API functionality."""

    def test_dashboard_requires_authentication(self, http_runner):
        """Test dashboard requires authentication."""
        response = http_runner.session.get(http_runner.base_url + '/dashboard', allow_redirects=False)

        # Should redirect to login
        assert response.status_code == 302, "Dashboard should require authentication"
        assert 'login' in response.headers.get('Location', '').lower()

    def test_authenticated_dashboard_access(self, clean_session):
        """Test authenticated user can access dashboard."""
        clean_session.login('admin', 'admin123')

        response = clean_session.get('/dashboard')
        assert response.status_code == 200, "Authenticated user should access dashboard"
        assert 'dashboard' in response.text.lower()

    def test_admin_only_results_access(self, clean_session):
        """Test only admins can access results."""
        # Test with voter account
        clean_session.login('voter1', 'password123')
        response = clean_session.session.get(clean_session.base_url + '/results', allow_redirects=False)
        assert response.status_code == 302, "Voter should not access results"

        clean_session.logout()

        # Test with admin account
        clean_session.login('admin', 'admin123')
        response = clean_session.get('/results')
        assert response.status_code == 200, "Admin should access results"