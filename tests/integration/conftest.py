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

    def __init__(self, base_url: str = "http://localhost"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        
        # Spoof a browser User-Agent to bypass CLI client blocking
        # (Server blocks curl, wget, httpie, python-requests, etc. for security)
        # Also set default Referer for Origin/Referer validation checks
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': self.base_url + '/login'  # Default Referer for security checks
        })

        # Rate limiting protection - add delay between requests
        self.last_request_time = 0
        self.min_request_delay = 0.1  # 100ms between requests

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
        # First get login page to ensure we have proper session
        response = self.get('/login')
        if response.status_code != 200:
            logging.error(f"Failed to GET /login: {response.status_code}")
            return False

        # Fetch the login nonce (required for security unless in TESTING mode)
        nonce_response = self.get('/login-nonce')
        nonce = None
        if nonce_response.status_code != 200:
            # If nonce endpoint fails, still try login (might be in TESTING mode)
            logging.warning(f"Failed to GET /login-nonce: {nonce_response.status_code}")
        else:
            try:
                nonce_data = nonce_response.json()
                nonce = nonce_data.get('nonce')
                logging.info(f"Successfully fetched nonce: {nonce[:20] if nonce else 'None'}...")
            except Exception as e:
                logging.error(f"Failed to parse nonce response JSON: {e}, response: {nonce_response.text[:200]}")
                nonce = None

        # Build login form data
        login_data = {
            'username': username,
            'password': password
        }
        
        # Include nonce if available
        if nonce:
            login_data['login_nonce'] = nonce
            logging.info(f"Attempting login for {username} with nonce")
        else:
            logging.warning(f"Attempting login for {username} WITHOUT nonce (may be in TESTING mode)")

        response = self.post('/login', data=login_data, allow_redirects=False)

        # Log the response for debugging
        logging.info(f"Login POST response status: {response.status_code}")
        if response.status_code != 302:
            logging.error(f"Login failed. Response text preview: {response.text[:300]}")

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
            logging.getLogger(__name__).debug("Handled exception in tests/integration/conftest.py", exc_info=True)
            return {
                'status': 'unhealthy',
                'response_time': time.time() - start_time,
                'status_code': None,
                'error': str(e)
            }

    def check_script_injection(self, payload: str) -> Dict[str, Any]:
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

    def check_sql_injection(self, payload: str) -> Dict[str, Any]:
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

    def check_xss_vulnerability(self, payload: str) -> Dict[str, Any]:
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
    """Pytest fixture for integration testing."""
    http_runner.session.cookies.clear()
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


@pytest.fixture(scope="module")
def mysql_split_app():
    """Create a real-MySQL app with independent runtime bind credentials.

    This fixture is intentionally opt-in and runs in a dedicated pytest process
    in CI. The normal test suite mutates SQLAlchemy metadata for its SQLite
    fixture, while this test must retain the production split-bind layout.
    """
    if os.environ.get("MYSQL_FLASK_INTEGRATION_TEST") != "1":
        pytest.skip("requires the dedicated CI MySQL Flask integration fixture")

    from datetime import date, datetime, timedelta, timezone
    from uuid import uuid4

    from sqlalchemy import event, text

    from app import create_app, db
    from app.models import Candidate, Election, ElectoralRoll, Region, Role, User

    app = create_app(
        {
            "TESTING": False,
            "PROPAGATE_EXCEPTIONS": True,
            "WTF_CSRF_ENABLED": False,
            "ENABLE_MFA": False,
            "DEBUG_DB_BIND": True,
        }
    )

    suffix = uuid4().hex[:12]
    voter_password = "Ci-Voter-Password!2026"
    manager_password = "Ci-Manager-Password!2026"
    seeded = {}

    with app.app_context():
        try:
            voter_role = Role.query.filter_by(name="voter").first()
            if voter_role is None:
                voter_role = Role(name="voter", description="Eligible voter")
                db.session.add(voter_role)

            manager_role = Role.query.filter_by(name="manager").first()
            if manager_role is None:
                manager_role = Role(name="manager", description="Election manager")
                db.session.add(manager_role)

            region = Region(name=f"CI split-bind region {suffix}")
            voter = User(
                username=f"ci_voter_{suffix}",
                email=f"ci-voter-{suffix}@example.invalid",
                driver_lic_no=f"CIVOTER{suffix}",
                driver_lic_state="VIC",
                role=voter_role,
                account_status="approved",
                email_verified=True,
            )
            voter.set_password(voter_password)
            voter.failed_login_attempts = 1
            manager = User(
                username=f"ci_manager_{suffix}",
                email=f"ci-manager-{suffix}@example.invalid",
                driver_lic_no=f"CIMANAGER{suffix}",
                driver_lic_state="VIC",
                role=manager_role,
                account_status="approved",
                email_verified=True,
            )
            manager.set_password(manager_password)
            manager.failed_login_attempts = 1

            enrolment = ElectoralRoll(
                roll_number=f"CI-ROLL-{suffix}",
                driver_license_number=f"CIVOTER{suffix}",
                full_name="CI Split Bind Voter",
                date_of_birth=date(1990, 1, 1),
                address_line1="1 Test Street",
                suburb="Melbourne",
                state="VIC",
                postcode="3000",
                region=region,
                status="active",
                verified=True,
                verified_at=datetime.now(timezone.utc).replace(tzinfo=None),
                user=voter,
            )
            db.session.add_all([region, voter, manager, enrolment])
            db.session.flush()

            open_election = Election(
                name=f"CI open election {suffix}",
                status="open",
                open_at=(datetime.now(timezone.utc) - timedelta(minutes=5)).replace(
                    tzinfo=None
                ),
                close_at=(datetime.now(timezone.utc) + timedelta(hours=1)).replace(
                    tzinfo=None
                ),
                created_by=manager.id,
            )
            open_candidate = Candidate(
                name="CI Open Candidate",
                party="Integration Test Party",
                position="Representative",
                region=region,
                election=open_election,
            )
            draft_election = Election(
                name=f"CI draft election {suffix}",
                status="draft",
                created_by=manager.id,
            )
            draft_candidate = Candidate(
                name="CI Draft Candidate",
                party="Integration Test Party",
                position="Representative",
                region=region,
                election=draft_election,
            )
            db.session.add_all(
                [
                    open_election,
                    open_candidate,
                    draft_election,
                    draft_candidate,
                ]
            )
            db.session.flush()
            from app.security.blind_signature import (
                ensure_election_blind_signing_key,
            )

            key_components = ensure_election_blind_signing_key(
                app.instance_path,
                open_election.id,
                None,
                allow_create=True,
            )
            open_election.blind_signing_key_id = key_components["key_id"]
            db.session.commit()
            seeded.update(
                {
                    "voter_id": voter.id,
                    "voter_username": voter.username,
                    "voter_password": voter_password,
                    "manager_id": manager.id,
                    "manager_username": manager.username,
                    "manager_password": manager_password,
                    "region_id": region.id,
                    "open_election_id": open_election.id,
                    "open_candidate_id": open_candidate.id,
                    "draft_election_id": draft_election.id,
                    "draft_candidate_id": draft_candidate.id,
                }
            )
        except Exception:
            db.session.rollback()
            raise
        finally:
            db.session.remove()

        engines = {
            "default": db.engines[None],
            "voters": db.engines["voters"],
            "admin": db.engines["admin"],
        }
        statements = {name: [] for name in engines}
        listeners = []

        for name, engine in engines.items():
            def record_statement(
                _connection,
                _cursor,
                statement,
                _parameters,
                _context,
                _executemany,
                *,
                bind_name=name,
            ):
                statements[bind_name].append(statement)

            event.listen(engine, "before_cursor_execute", record_statement)
            listeners.append((engine, record_statement))

    try:
        yield {
            "app": app,
            "engines": engines,
            "statements": statements,
            **seeded,
        }
    finally:
        with app.app_context():
            db.session.remove()
            for engine, listener in listeners:
                event.remove(engine, "before_cursor_execute", listener)

            cleanup_params = {
                "open_election_id": seeded["open_election_id"],
                "draft_election_id": seeded["draft_election_id"],
                "voter_id": seeded["voter_id"],
                "manager_id": seeded["manager_id"],
                "region_id": seeded["region_id"],
            }
            with engines["default"].begin() as connection:
                connection.execute(
                    text(
                        "DELETE FROM vote_receipt WHERE election_id IN "
                        "(:open_election_id, :draft_election_id)"
                    ),
                    cleanup_params,
                )
                connection.execute(
                    text(
                        "DELETE FROM blind_signature_token WHERE election_id IN "
                        "(:open_election_id, :draft_election_id)"
                    ),
                    cleanup_params,
                )
                connection.execute(
                    text(
                        "DELETE FROM spent_ballot_nullifier WHERE election_id IN "
                        "(:open_election_id, :draft_election_id)"
                    ),
                    cleanup_params,
                )
                connection.execute(
                    text(
                        "DELETE FROM vote WHERE election_id IN "
                        "(:open_election_id, :draft_election_id)"
                    ),
                    cleanup_params,
                )
                connection.execute(
                    text(
                        "DELETE FROM candidate WHERE election_id IN "
                        "(:open_election_id, :draft_election_id)"
                    ),
                    cleanup_params,
                )
                connection.execute(
                    text(
                        "DELETE FROM election WHERE id IN "
                        "(:open_election_id, :draft_election_id)"
                    ),
                    cleanup_params,
                )
                connection.execute(
                    text("DELETE FROM electoral_roll WHERE user_id = :voter_id"),
                    cleanup_params,
                )
                connection.execute(
                    text(
                        "DELETE FROM user WHERE id IN (:voter_id, :manager_id)"
                    ),
                    cleanup_params,
                )
                connection.execute(
                    text("DELETE FROM regions WHERE id = :region_id"),
                    cleanup_params,
                )
