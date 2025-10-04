"""
Smoke tests for the voting application.
These tests verify basic functionality works correctly.
"""

import pytest
from flask import url_for
from app.models import User, Candidate, Vote


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
        assert b'Voter Sign In' in response.data

    def test_successful_login(self, client):
        """Test successful login with test credentials."""
        # First, ensure test user exists
        with client.application.app_context():
            user = User.query.filter_by(username='testuser').first()
            assert user is not None

        # Attempt login
        response = client.post('/login', data={
            'username': 'testuser',
            'password': 'testpass'
        }, follow_redirects=True)

        assert response.status_code == 200
        # Should redirect to dashboard after successful login
        assert b'Welcome, testuser' in response.data

    def test_failed_login(self, client):
        """Test login with invalid credentials."""
        response = client.post('/login', data={
            'username': 'testuser',
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
            'username': 'testuser',
            'password': 'testpass'
        })

        # Access dashboard
        response = client.get('/dashboard')
        assert response.status_code == 200
        assert b'Alice Johnson' in response.data
        assert b'Bob Smith' in response.data

    def test_voting_functionality(self, client):
        """Test the complete voting process."""
        with client.application.app_context():
            candidate = Candidate.query.filter_by(name='Alice Johnson').first()
            assert candidate is not None

        # Login
        client.post('/login', data={
            'username': 'testuser',
            'password': 'testpass'
        })

        # Vote for candidate
        response = client.post('/vote', data={
            'candidate_id': candidate.id
        }, follow_redirects=True)

        assert response.status_code == 200
        # Should show "Thank you for voting!" on dashboard after voting
        assert b'Thank you for voting!' in response.data

        # Verify vote was recorded
        with client.application.app_context():
            user = User.query.filter_by(username='testuser').first()
            vote = Vote.query.filter_by(user_id=user.id).first()
            assert vote is not None
            assert vote.candidate_id == candidate.id

    def test_admin_results_access(self, client):
        """Test that admin can access results page."""
        # Login as admin
        client.post('/login', data={
            'username': 'admin',
            'password': 'adminpass'
        })

        # Access results
        response = client.get('/results')
        assert response.status_code == 200
        assert b'Results' in response.data

    def test_non_admin_cannot_access_results(self, client):
        """Test that regular users cannot access results page."""
        # Login as regular user
        client.post('/login', data={
            'username': 'testuser',
            'password': 'testpass'
        })

        # Try to access results - should redirect to dashboard
        response = client.get('/results', follow_redirects=True)
        assert response.status_code == 200
        # Should be redirected to dashboard
        assert b'Welcome, testuser' in response.data

    def test_logout_functionality(self, client):
        """Test logout functionality."""
        # Login first
        client.post('/login', data={
            'username': 'testuser',
            'password': 'testpass'
        })

        # Logout
        response = client.get('/logout', follow_redirects=True)
        assert response.status_code == 200

        # Try to access dashboard (should redirect to login)
        response = client.get('/dashboard')
        assert response.status_code == 302
        assert '/login' in response.headers['Location']

    def test_prevent_double_voting(self, client):
        """Test that users cannot vote twice."""
        with client.application.app_context():
            candidate = Candidate.query.filter_by(name='Alice Johnson').first()

        # Login and vote
        client.post('/login', data={
            'username': 'testuser',
            'password': 'testpass'
        })

        # First vote
        client.post('/vote', data={'candidate_id': candidate.id})

        # Try to vote again
        response = client.post('/vote', data={'candidate_id': candidate.id}, follow_redirects=True)
        assert response.status_code == 200
        # Should still show "Thank you for voting!" since user has already voted
        assert b'Thank you for voting!' in response.data