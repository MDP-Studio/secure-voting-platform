"""
Integration Test Framework for Voting System Security Testing

This module provides a base HTTP test runner for integration, regression,
and penetration testing against running Docker containers.

Test Runners Comparison:
- Cypress: Excellent for E2E browser testing, but overkill for pure API testing
- Newman: Good for Postman collection testing, but less flexible for custom security tests
- Python (pytest + requests): Most appropriate here because:
  * Already used in project
  * Excellent for API testing
  * Flexible for security/penetration testing
  * Easy Docker container testing
  * Great CI/CD integration
  * Can handle both positive and negative test cases
"""

import pytest
import requests
import json
import time
import logging
from typing import Dict, Any, Optional
from urllib.parse import urljoin


class HTTPTestRunner:
    """
    Base HTTP test runner for integration testing against Docker containers.

    Provides common functionality for:
    - Health checks
    - Authentication flows
    - Security testing (XSS, SQL injection, script injection)
    - API endpoint testing
    """

    def __init__(self, base_url: str = "http://localhost:5000"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.timeout = 10  # 10 second timeout

        # Rate limiting protection - add delay between requests
        self.last_request_time = 0
        self.min_request_delay = 0.1  # 100ms between requests

        # Test user credentials
        self.test_users = {
            'admin': {'username': 'admin', 'password': 'admin123'},
            'voter': {'username': 'voter1', 'password': 'VoterSecurePass123!'}
        }

    def _rate_limit_delay(self):
        """Add delay between requests to avoid rate limiting."""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.min_request_delay:
            time.sleep(self.min_request_delay - time_since_last_request)
        self.last_request_time = time.time()

    def get(self, path: str, **kwargs) -> requests.Response:
        """Make GET request to API endpoint."""
        self._rate_limit_delay()
        url = urljoin(self.base_url + '/', path.lstrip('/'))
        return self.session.get(url, **kwargs)

    def post(self, path: str, data=None, json=None, **kwargs) -> requests.Response:
        """Make POST request to API endpoint."""
        self._rate_limit_delay()
        url = urljoin(self.base_url + '/', path.lstrip('/'))
        return self.session.post(url, data=data, json=json, **kwargs)

    def login(self, username: str, password: str) -> bool:
        """Attempt login and return success status."""
        # First get login page to get CSRF token if needed
        response = self.get('/login')
        if response.status_code != 200:
            return False

        # For now, simple login (may need OTP handling)
        login_data = {
            'username': username,
            'password': password
        }

        response = self.post('/login', data=login_data, allow_redirects=False)

        # Success: 302 redirect to dashboard
        # Failure: 200 with login form shown again
        if response.status_code == 302:
            location = response.headers.get('Location', '')
            return 'dashboard' in location.lower()
        elif response.status_code == 200:
            # Check if we're still on login page (failed login)
            return 'login' not in response.text.lower()

        return False

    def logout(self):
        """Logout current user."""
        response = self.get('/logout')
        # Check if logout was successful by looking for redirect to login
        return response.status_code == 302 and 'login' in response.headers.get('Location', '')

    def is_authenticated(self) -> bool:
        """Check if current session is authenticated."""
        response = self.session.get(self.base_url + '/dashboard', allow_redirects=False)
        # Consider authenticated if we get a 200 response (not redirect to login)
        return response.status_code == 200

    def health_check(self) -> Dict[str, Any]:
        """Perform basic health check."""
        start_time = time.time()
        try:
            response = self.get('/', timeout=5)
            response_time = time.time() - start_time

            return {
                'status': 'healthy' if response.status_code == 200 else 'unhealthy',
                'response_time': round(response_time, 3),
                'status_code': response.status_code,
                'error': None
            }
        except requests.RequestException as e:
            return {
                'status': 'unhealthy',
                'response_time': time.time() - start_time,
                'status_code': None,
                'error': str(e)
            }

    def test_script_injection(self, payload: str) -> Dict[str, Any]:
        """Test for script injection vulnerabilities."""
        # Test in login form
        test_data = {
            'username': payload,
            'password': 'test123'
        }

        response = self.post('/login', data=test_data)
        injected = payload.lower() in response.text.lower()

        return {
            'payload': payload,
            'injected': injected,
            'status_code': response.status_code,
            'response_contains_payload': injected
        }

    def test_sql_injection(self, payload: str) -> Dict[str, Any]:
        """Test for SQL injection vulnerabilities."""
        # Test in login form
        test_data = {
            'username': payload,
            'password': 'test123'
        }

        response = self.post('/login', data=test_data)

        # Check for common SQL error patterns
        error_patterns = [
            'sql', 'syntax', 'mysql', 'sqlite', 'postgresql',
            'ORA-', 'SQLSTATE', 'syntax error'
        ]

        # Find which specific error patterns were detected
        detected_errors = []
        response_text_lower = response.text.lower()
        for pattern in error_patterns:
            if pattern in response_text_lower:
                detected_errors.append(pattern)

        has_error = len(detected_errors) > 0

        # Log the specific error patterns found
        if has_error:
            logging.info(f"SQL error patterns detected in response for payload '{payload}': {detected_errors}")
            # Log the actual response content for verification
            logging.info(f"Response content (first 500 chars): {response.text[:500]}")
            if len(response.text) > 500:
                logging.info(f"... (response truncated, total length: {len(response.text)})")

        return {
            'payload': payload,
            'sql_error_detected': has_error,
            'detected_errors': detected_errors,
            'status_code': response.status_code,
            'response_content': response.text  # Include full response for debugging
        }

    def test_xss_vulnerability(self, payload: str) -> Dict[str, Any]:
        """Test for XSS vulnerabilities."""
        # Test in various input fields
        test_data = {
            'username': payload,
            'password': 'test123'
        }

        response = self.post('/login', data=test_data)

        # Check if request was blocked by WAF (403 status)
        waf_blocked = response.status_code == 403

        # Check if payload appears unescaped in response (only if not blocked)
        unescaped = False
        if not waf_blocked:
            unescaped = payload in response.text

        # Find where the payload appears in the response for debugging
        payload_locations = []
        if unescaped:
            # Look for script tags, event handlers, etc.
            dangerous_patterns = ['<script', 'javascript:', 'onload=', 'onerror=', 'onclick=']
            for pattern in dangerous_patterns:
                if pattern in response.text.lower():
                    payload_locations.append(pattern)

        # Log WAF blocking or vulnerability detection
        if waf_blocked:
            logging.info(f"XSS attempt blocked by WAF: {payload} (403 Forbidden)")
        elif unescaped:
            logging.warning(f"XSS payload appears unescaped in response for payload: {payload}")
            if payload_locations:
                logging.warning(f"Dangerous patterns found: {payload_locations}")
            # Log the actual response content for verification
            logging.warning(f"Response content (first 500 chars): {response.text[:500]}")
            if len(response.text) > 500:
                logging.warning(f"... (response truncated, total length: {len(response.text)})")

        return {
            'payload': payload,
            'xss_possible': unescaped,
            'waf_blocked': waf_blocked,
            'dangerous_patterns': payload_locations,
            'status_code': response.status_code,
            'response_content': response.text  # Include full response for debugging
        }