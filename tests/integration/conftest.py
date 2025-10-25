"""
Integration test configuration and fixtures.

This conftest.py provides fixtures for integration testing against
running Docker containers with the WAF enabled.
"""

import pytest
import requests
import json
import time
import logging
import os
from typing import Dict, Any, Optional
from urllib.parse import urljoin


# Configure logging to write to tests.log file
def pytest_configure(config):
    """Configure pytest logging to write to file."""
    # Create logs directory if it doesn't exist
    log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
    os.makedirs(log_dir, exist_ok=True)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(os.path.join(log_dir, 'tests.log'), mode='a'),
            logging.StreamHandler()  # Keep console output too
        ]
    )


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

        # Success: 302 redirect to appropriate dashboard based on role
        # - voters: /dashboard
        # - delegates: /delegate  
        # - managers: /dev/dashboard
        # Failure: 200 with login form shown again
        if response.status_code == 302:
            location = response.headers.get('Location', '')
            # Accept any dashboard redirect as success
            return any(dashboard in location for dashboard in ['/dashboard', '/delegate', '/dev/dashboard'])
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

        # Check if payload appears unescaped in response
        unescaped = payload in response.text

        # Find where the payload appears in the response for debugging
        payload_locations = []
        if unescaped:
            # Look for script tags, event handlers, etc.
            dangerous_patterns = ['<script', 'javascript:', 'onload=', 'onerror=', 'onclick=']
            for pattern in dangerous_patterns:
                if pattern in response.text.lower():
                    payload_locations.append(pattern)

        if unescaped:
            logging.info(f"XSS payload appears unescaped in response for payload: {payload}")
            if payload_locations:
                logging.info(f"Dangerous patterns found: {payload_locations}")
            # Log the actual response content for verification
            logging.info(f"Response content (first 500 chars): {response.text[:500]}")
            if len(response.text) > 500:
                logging.info(f"... (response truncated, total length: {len(response.text)})")

        return {
            'payload': payload,
            'xss_possible': unescaped,
            'dangerous_patterns': payload_locations,
            'status_code': response.status_code,
            'response_content': response.text  # Include full response for debugging
        }


@pytest.fixture(scope="session")
def http_runner(request):
    """Pytest fixture providing HTTP test runner instance."""
    # Use localhost (port 80) for Docker WAF setup, localhost:5000 for local Flask
    base_url = request.config.getoption("--base-url")
    return HTTPTestRunner(base_url)


@pytest.fixture(scope="function")
def clean_session(http_runner):
    """Pytest fixture ensuring clean session for each test."""
    http_runner.session.cookies.clear()
    yield http_runner
    http_runner.session.cookies.clear()


@pytest.fixture(scope="function")
def clean_session_with_retry(http_runner):
    """Pytest fixture with automatic retry on rate limiting."""
    http_runner.session.cookies.clear()
    # Add test mode header to relax rate limiting
    http_runner.session.headers.update({'X-Test-Mode': '1'})
    yield http_runner
    http_runner.session.cookies.clear()


@pytest.fixture(scope="function")
def direct_app_session():
    """Pytest fixture that bypasses WAF entirely for direct app testing."""
    runner = HTTPTestRunner("http://localhost:8000")
    runner.session.cookies.clear()
    yield runner
    runner.session.cookies.clear()


@pytest.fixture(scope="function")
def rate_limit_aware_session(http_runner):
    """Pytest fixture that handles rate limiting gracefully."""
    http_runner.session.cookies.clear()
    # Store original post method
    original_post = http_runner.post

    def rate_limit_resilient_post(path, data=None, json=None, **kwargs):
        """Post method that retries on rate limiting."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = original_post(path, data=data, json=json, **kwargs)
                if response.status_code == 503:
                    # Check if it's rate limiting (nginx returns 503 for rate limits)
                    if attempt < max_retries - 1:
                        import time
                        wait_time = 2 ** attempt  # Exponential backoff
                        print(f"Rate limited (attempt {attempt + 1}), waiting {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        # On final attempt, consider rate limiting as expected behavior
                        print(f"Rate limiting detected after {max_retries} attempts - this may be expected security behavior")
                        return response
                return response
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                continue

    # Monkey patch the post method
    http_runner.post = rate_limit_resilient_post
    yield http_runner
    # Restore original method
    http_runner.post = original_post
    http_runner.session.cookies.clear()