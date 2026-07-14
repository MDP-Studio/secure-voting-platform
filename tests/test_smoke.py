"""
Smoke tests for the voting application.
These tests verify basic functionality works correctly.
"""

from flask import url_for
from app.models import User, Candidate, Vote, VoteReceipt


class TestSmokeTests:
    """Basic smoke tests to ensure the application works."""

    def test_app_creation(self, app):
        """Test that the app can be created successfully."""
        assert app is not None
        assert app.config['TESTING'] is True

    def test_database_initialization(self, app):
        """Test that the database is properly initialized."""
        with app.app_context():
            # Check that tables exist
            assert User.query.count() >= 0
            assert Candidate.query.count() >= 0
            assert Vote.query.count() >= 0

    def test_home_page_redirects_to_login(self, client):
        """Test that the home page redirects to login."""
        response = client.get('/')
        assert response.status_code == 302  # Redirect
        assert '/login' in response.headers['Location']

    def test_login_page_loads(self, client):
        """Test that the login page loads successfully."""
        response = client.get('/login')
        assert response.status_code == 200
        assert b'Sign in' in response.data or b'SecureVote' in response.data

    def test_public_threat_model_page_loads(self, client):
        """Test that the public threat model summary is reviewable without login."""
        response = client.get('/threat-model')
        assert response.status_code == 200
        assert b'SecureVote Threat Model' in response.data
        assert b'Residual Risks and Non-Claims' in response.data
        assert b'tests/test_blind_signature.py' in response.data

    def test_successful_login(self, client):
        """Test successful login with test credentials."""
        # First, ensure test user exists
        with client.application.app_context():
            user = User.query.filter_by(username='voter1').first()
            assert user is not None

        # Attempt login
        response = client.post('/login', data={
            'username': 'voter1',
            'password': 'Password@123!'
        }, follow_redirects=True)

        assert response.status_code == 200
        # Should redirect to dashboard after successful login
        assert b'voter1' in response.data

    def test_failed_login(self, client):
        """Test login with invalid credentials."""
        response = client.post('/login', data={
            'username': 'voter1',
            'password': 'wrongpassword'
        }, follow_redirects=True)

        assert response.status_code == 200
        assert b'Invalid username or password' in response.data

    def test_dashboard_requires_login(self, client):
        """Test that dashboard requires authentication."""
        response = client.get('/dashboard')
        assert response.status_code == 302  # Redirect to login
        assert '/login' in response.headers['Location']

    def test_dashboard_shows_candidates(self, client):
        """Test that dashboard shows available candidates after login."""
        # Login first
        client.post('/login', data={
            'username': 'voter1',
            'password': 'Password@123!'
        })

        # Access dashboard
        response = client.get('/dashboard')
        assert response.status_code == 200
        assert b'John Smith' in response.data
        assert b'Sarah Johnson' in response.data

    def test_voting_functionality(self, client):
        """The retired identity-linked form endpoint cannot record a ballot."""
        with client.application.app_context():
            candidate = Candidate.query.filter_by(name='John Smith').first()
            assert candidate is not None

        # Login
        client.post('/login', data={
            'username': 'voter1',
            'password': 'Password@123!'
        })

        # Direct form voting is deliberately disabled.
        response = client.post('/vote', data={
            'candidate_id': candidate.id
        })

        assert response.status_code == 410
        # The endpoint explains the supported anonymous path.
        assert b'Direct ballot submission is disabled' in response.data

        # Verify the retired endpoint wrote no identity receipt or ballot.
        with client.application.app_context():
            user = User.query.filter_by(username='voter1').first()
            assert VoteReceipt.query.filter_by(
                user_id=user.id,
                election_id=candidate.election_id,
            ).count() == 0
            # The Vote table no longer stores user_id; verify a vote exists for the candidate
            assert Vote.query.filter_by(candidate_id=candidate.id).count() == 0

    def test_admin_results_access(self, client):
        """Test that admin can access results page."""
        # Login as admin
        client.post('/login', data={
            'username': 'admin',
            'password': 'Admin@123456!'
        })

        # Access results
        response = client.get('/results')
        assert response.status_code == 200
        assert b'Results' in response.data

    def test_non_admin_cannot_access_results(self, client):
        """Test that regular users cannot access results page."""
        # Login as regular user
        client.post('/login', data={
            'username': 'voter1',
            'password': 'Password@123!'
        })

        # Try to access results - should be denied (redirect or 403)
        response = client.get('/results')
        assert response.status_code in (302, 403)

    def test_logout_functionality(self, client):
        """Test logout functionality."""
        # Login first
        client.post('/login', data={
            'username': 'voter1',
            'password': 'Password@123!'
        })

        # Logout
        response = client.get('/logout', follow_redirects=True)
        assert response.status_code == 200
        assert b'Sign in' in response.data or b'SecureVote' in response.data

        # Try to access dashboard (should redirect to login)
        response = client.get('/dashboard')
        assert response.status_code == 302
        assert '/login' in response.headers['Location']

    def test_prevent_double_voting(self, client):
        """Repeated direct submissions remain disabled and side-effect free."""
        with client.application.app_context():
            candidate = Candidate.query.filter_by(name='John Smith').first()

        # Login and vote
        client.post('/login', data={
            'username': 'voter1',
            'password': 'Password@123!'
        })

        first = client.post('/vote', data={'candidate_id': candidate.id})
        assert first.status_code == 410

        second = client.post('/vote', data={'candidate_id': candidate.id})
        assert second.status_code == 410
        assert b'Direct ballot submission is disabled' in second.data

        with client.application.app_context():
            user = User.query.filter_by(username='voter1').one()
            assert VoteReceipt.query.filter_by(
                user_id=user.id,
                election_id=candidate.election_id,
            ).count() == 0
            assert Vote.query.filter_by(election_id=candidate.election_id).count() == 0

    def test_developer_dashboard_denied_from_remote(self, client):
        """Test that developer dashboard denies access from non-localhost."""
        response = client.get(
            '/dev/dashboard',
            environ_base={'REMOTE_ADDR': '203.0.113.10'},
        )
        assert response.status_code == 403

    def test_developer_dashboard_allowed_from_localhost(self, client):
        """Test that developer dashboard allows access from localhost."""
        response = client.get(
            '/dev/dashboard',
            environ_base={'REMOTE_ADDR': '127.0.0.1'},
        )
        assert response.status_code == 200
