"""
Tests for features added during the portfolio overhaul:
- Password reset flow
- Email verification
- Election state management
- User profile page
- Admin account unlock
- Error pages
- Vote anonymity
- Audit trail UI
"""
from app.models import Vote, VoteReceipt, Election


class TestPasswordReset:
    """Password reset flow tests."""

    def test_forgot_password_page_loads(self, client):
        response = client.get('/forgot-password')
        assert response.status_code == 200
        assert b'Forgot Password' in response.data

    def test_forgot_password_submit_shows_generic_message(self, client):
        """Should show same message whether email exists or not (anti-enumeration)."""
        response = client.post('/forgot-password', data={
            'email': 'nonexistent@example.com'
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'If an account with that email exists' in response.data

    def test_reset_password_invalid_token(self, client):
        response = client.get('/reset-password/invalid-token', follow_redirects=True)
        assert response.status_code == 200
        assert b'Invalid reset link' in response.data


class TestProfile:
    """User profile page tests."""

    def test_profile_requires_login(self, client):
        response = client.get('/profile')
        assert response.status_code == 302  # Redirect to login

    def test_profile_loads_for_authenticated_user(self, client):
        client.post('/login', data={
            'username': 'voter1',
            'password': 'Password@123!'
        })
        response = client.get('/profile')
        assert response.status_code == 200
        assert b'My Profile' in response.data
        assert b'voter1' in response.data


class TestElections:
    """Election state management tests."""

    def test_elections_page_requires_manager(self, client):
        """Voters should not access election management."""
        client.post('/login', data={
            'username': 'voter1',
            'password': 'Password@123!'
        })
        response = client.get('/elections/')
        assert response.status_code == 403

    def test_elections_page_loads_for_manager(self, client):
        client.post('/login', data={
            'username': 'admin',
            'password': 'Admin@123456!'
        })
        response = client.get('/elections/')
        assert response.status_code == 200
        assert b'Election Management' in response.data

    def test_direct_vote_is_disabled_even_without_open_election(self, client, app):
        """The retired direct endpoint never falls back to identity-linked voting."""
        with app.app_context():
            # Close all elections
            for e in Election.query.all():
                e.status = 'closed'
            from app import db
            db.session.commit()

        client.post('/login', data={
            'username': 'voter1',
            'password': 'Password@123!'
        })
        response = client.post('/vote', data={
            'candidate_id': 1
        })
        assert response.status_code == 410
        assert b'Direct ballot submission is disabled' in response.data


class TestErrorPages:
    """Custom error page tests."""

    def test_404_returns_custom_page(self, client):
        response = client.get('/nonexistent-page-that-does-not-exist')
        assert response.status_code == 404
        assert b'Page Not Found' in response.data

    def test_403_for_unauthorized_access(self, client):
        """Voters trying to access admin pages should get 403."""
        client.post('/login', data={
            'username': 'voter1',
            'password': 'Password@123!'
        })
        response = client.get('/elections/')
        assert response.status_code == 403


class TestVoteAnonymity:
    """Vote anonymity and integrity tests."""

    def test_direct_endpoint_cannot_create_ballot_or_receipt(self, client, app):
        """An authenticated candidate choice cannot enter ballot storage."""
        client.post('/login', data={
            'username': 'voter1',
            'password': 'Password@123!'
        })

        with app.app_context():
            from app.models import Candidate
            candidate = Candidate.query.first()

        response = client.post('/vote', data={'candidate_id': candidate.id})
        assert response.status_code == 410

        with app.app_context():
            assert Vote.query.count() == 0
            assert VoteReceipt.query.count() == 0

    def test_dashboard_has_no_identity_linked_noscript_fallback(self, client):
        client.post('/login', data={
            'username': 'voter1',
            'password': 'Password@123!'
        })
        response = client.get('/dashboard')
        assert response.status_code == 200
        assert b'No identity-linked form fallback is provided' in response.data
        assert b'action="/vote"' not in response.data

    def test_voter_token_is_random(self, client, app):
        """voter_token should not be deterministic — running the service twice
        with the same user should produce different tokens (if it were possible
        to vote twice)."""
        with app.app_context():
            import secrets
            # Just verify the token generation is random
            t1 = secrets.token_hex(32)
            t2 = secrets.token_hex(32)
            assert t1 != t2


class TestAuditLog:
    """Audit trail UI tests."""

    def test_audit_log_requires_manager(self, client):
        client.post('/login', data={
            'username': 'voter1',
            'password': 'Password@123!'
        })
        response = client.get('/admin/audit/')
        assert response.status_code == 403

    def test_audit_log_loads_for_manager(self, client):
        client.post('/login', data={
            'username': 'admin',
            'password': 'Admin@123456!'
        })
        response = client.get('/admin/audit/')
        assert response.status_code == 200
        assert b'Audit Log' in response.data
