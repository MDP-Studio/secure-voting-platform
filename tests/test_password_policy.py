"""
Tests for password policy enforcement features.

This test suite validates:
- Account lockout after failed login attempts
- Password expiration after 90 days
- Password change functionality
- Password history (if implemented)
"""

import pytest
from datetime import datetime, timedelta
from app import create_app, db
from app.models import User, Role


@pytest.fixture
def app():
    """Create and configure a test Flask app."""
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,
        'SECRET_KEY': 'test-secret-key',
        'ENABLE_MFA': False,  # Disable MFA for simpler testing
    })
    
    with app.app_context():
        db.create_all()
        
        # Create roles
        voter_role = Role(name='voter', description='Voter role')
        db.session.add(voter_role)
        db.session.commit()
        
        yield app
        
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()


@pytest.fixture
def test_user(app):
    """Create a test user."""
    with app.app_context():
        voter_role = Role.query.filter_by(name='voter').first()
        user = User(
            username='testuser',
            email='test@example.com',
            driver_lic_no='ABC123456',
            driver_lic_state='VIC',
            role_id=voter_role.id
        )
        user.set_password('SecureTestPass123!')
        db.session.add(user)
        db.session.commit()
        return user


class TestAccountLockout:
    """Test account lockout after failed login attempts."""
    
    def test_account_locks_after_5_failed_attempts(self, app, client, test_user):
        """Test that account locks after 5 failed login attempts."""
        with app.app_context():
            # Attempt 5 failed logins
            for i in range(5):
                response = client.post('/login', data={
                    'username': 'testuser',
                    'password': 'WrongPassword123!'
                }, follow_redirects=True)
                assert response.status_code == 200
            
            # Check that account is now locked
            user = User.query.filter_by(username='testuser').first()
            assert user.is_account_locked() is True
            assert user.failed_login_attempts >= 5
            assert user.account_locked_until is not None
    
    def test_cannot_login_when_account_locked(self, app, client, test_user):
        """Test that login is prevented when account is locked."""
        with app.app_context():
            # Lock the account
            user = User.query.filter_by(username='testuser').first()
            user.account_locked_until = datetime.utcnow() + timedelta(minutes=30)
            user.failed_login_attempts = 5
            db.session.commit()
            
            # Try to login with correct password
            response = client.post('/login', data={
                'username': 'testuser',
                'password': 'SecureTestPass123!'
            }, follow_redirects=True)
            
            assert b'Account is locked' in response.data
    
    def test_account_unlocks_after_timeout(self, app, test_user):
        """Test that account unlocks after the lockout period expires."""
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            
            # Set lockout to expire in the past
            user.account_locked_until = datetime.utcnow() - timedelta(minutes=1)
            user.failed_login_attempts = 5
            db.session.commit()
            
            # Account should no longer be locked
            assert user.is_account_locked() is False
    
    def test_failed_attempts_reset_on_successful_login(self, app, client, test_user):
        """Test that failed login counter resets after successful login."""
        with app.app_context():
            # Record some failed attempts
            user = User.query.filter_by(username='testuser').first()
            user.failed_login_attempts = 3
            db.session.commit()
            
            # Successful login
            response = client.post('/login', data={
                'username': 'testuser',
                'password': 'SecureTestPass123!'
            }, follow_redirects=True)
            
            # Check that counter is reset
            user = User.query.filter_by(username='testuser').first()
            assert user.failed_login_attempts == 0
            assert user.account_locked_until is None


class TestPasswordExpiration:
    """Test password expiration after 90 days."""
    
    def test_password_not_expired_when_recent(self, app, test_user):
        """Test that recent passwords are not expired."""
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            user.password_changed_at = datetime.utcnow() - timedelta(days=30)
            db.session.commit()
            
            assert user.is_password_expired() is False
    
    def test_password_expired_after_90_days(self, app, test_user):
        """Test that password expires after 90 days."""
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            user.password_changed_at = datetime.utcnow() - timedelta(days=91)
            db.session.commit()
            
            assert user.is_password_expired() is True
    
    def test_password_expired_when_no_timestamp(self, app, test_user):
        """Test that password is considered expired when no timestamp exists."""
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            user.password_changed_at = None
            db.session.commit()
            
            assert user.is_password_expired() is True
    
    def test_redirect_to_change_password_when_expired(self, app, client, test_user):
        """Test that users are redirected to change password when expired."""
        with app.app_context():
            # Set password as expired
            user = User.query.filter_by(username='testuser').first()
            user.password_changed_at = datetime.utcnow() - timedelta(days=91)
            db.session.commit()
            
            # Try to login
            response = client.post('/login', data={
                'username': 'testuser',
                'password': 'TestPassword123!'
            }, follow_redirects=False)
            
            # Should redirect to change password
            assert response.status_code == 302
            assert '/change-password' in response.location


class TestPasswordChange:
    """Test password change functionality."""
    
    def test_password_change_requires_login(self, client):
        """Test that password change page requires authentication."""
        response = client.get('/change-password')
        assert response.status_code == 302  # Redirect to login
    
    def test_password_change_with_correct_current_password(self, app, client, test_user):
        """Test successful password change."""
        with app.app_context():
            # Login first
            client.post('/login', data={
                'username': 'testuser',
                'password': 'SecureTestPass123!'
            })
            
            # Change password
            response = client.post('/change-password', data={
                'current_password': 'SecureTestPass123!',
                'new_password': 'NewSecurePass456!',
                'confirm_password': 'NewSecurePass456!'
            }, follow_redirects=True)
            
            assert response.status_code == 200
            assert b'Password changed successfully' in response.data
            
            # Verify new password works
            user = User.query.filter_by(username='testuser').first()
            assert user.check_password('NewSecurePass456!') is True
            assert user.check_password('SecureTestPass123!') is False
    
    def test_password_change_fails_with_wrong_current_password(self, app, client, test_user):
        """Test that password change fails with incorrect current password."""
        with app.app_context():
            # Login first
            client.post('/login', data={
                'username': 'testuser',
                'password': 'SecureTestPass123!'
            })
            
            # Try to change password with wrong current password
            response = client.post('/change-password', data={
                'current_password': 'WrongPassword123!',
                'new_password': 'NewSecurePass456!',
                'confirm_password': 'NewSecurePass456!'
            }, follow_redirects=True)
            
            assert b'Current password is incorrect' in response.data
    
    def test_password_change_fails_when_passwords_dont_match(self, app, client, test_user):
        """Test that password change fails when new passwords don't match."""
        with app.app_context():
            # Login first
            client.post('/login', data={
                'username': 'testuser',
                'password': 'SecureTestPass123!'
            })
            
            # Try to change password with mismatched new passwords
            response = client.post('/change-password', data={
                'current_password': 'SecureTestPass123!',
                'new_password': 'NewSecurePass456!',
                'confirm_password': 'DifferentSecurePass456!'
            }, follow_redirects=True)
            
            assert b'do not match' in response.data
    
    def test_password_change_fails_with_same_password(self, app, client, test_user):
        """Test that password change fails when new password is same as current."""
        with app.app_context():
            # Login first
            client.post('/login', data={
                'username': 'testuser',
                'password': 'SecureTestPass123!'
            })
            
            # Try to change password to the same password
            response = client.post('/change-password', data={
                'current_password': 'SecureTestPass123!',
                'new_password': 'SecureTestPass123!',
                'confirm_password': 'SecureTestPass123!'
            }, follow_redirects=True)
            
            assert b'must be different from current password' in response.data
    
    def test_password_change_fails_with_weak_password(self, app, client, test_user):
        """Test that password change fails with weak password."""
        with app.app_context():
            # Login first
            client.post('/login', data={
                'username': 'testuser',
                'password': 'SecureTestPass123!'
            })
            
            # Try to change to weak password
            response = client.post('/change-password', data={
                'current_password': 'SecureTestPass123!',
                'new_password': 'weak',
                'confirm_password': 'weak'
            }, follow_redirects=True)
            
            assert b'Password validation failed' in response.data
    
    def test_password_changed_at_updates(self, app, client, test_user):
        """Test that password_changed_at timestamp updates on password change."""
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            old_timestamp = user.password_changed_at
            
            # Login first
            client.post('/login', data={
                'username': 'testuser',
                'password': 'SecureTestPass123!'
            })
            
            # Wait a moment to ensure timestamp difference
            import time
            time.sleep(1)
            
            # Change password
            client.post('/change-password', data={
                'current_password': 'SecureTestPass123!',
                'new_password': 'NewSecurePass456!',
                'confirm_password': 'NewSecurePass456!'
            })
            
            # Check timestamp was updated
            user = User.query.filter_by(username='testuser').first()
            assert user.password_changed_at > old_timestamp


class TestUserModelPasswordMethods:
    """Test User model password-related methods."""
    
    def test_set_password_updates_timestamp(self, app, test_user):
        """Test that set_password updates password_changed_at."""
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            old_timestamp = user.password_changed_at
            
            import time
            time.sleep(1)
            
            user.set_password('NewPassword789!')
            db.session.commit()
            
            assert user.password_changed_at > old_timestamp
    
    def test_set_password_resets_failed_attempts(self, app, test_user):
        """Test that set_password resets failed login attempts."""
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            user.failed_login_attempts = 3
            user.account_locked_until = datetime.utcnow() + timedelta(minutes=30)
            
            user.set_password('NewPassword789!')
            db.session.commit()
            
            assert user.failed_login_attempts == 0
            assert user.account_locked_until is None
    
    def test_record_failed_login_increments_counter(self, app, test_user):
        """Test that record_failed_login increments the counter."""
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            initial_attempts = user.failed_login_attempts
            
            user.record_failed_login()
            
            assert user.failed_login_attempts == initial_attempts + 1
    
    def test_reset_failed_logins_clears_counter(self, app, test_user):
        """Test that reset_failed_logins clears the counter."""
        with app.app_context():
            user = User.query.filter_by(username='testuser').first()
            user.failed_login_attempts = 5
            user.account_locked_until = datetime.utcnow() + timedelta(minutes=30)
            
            user.reset_failed_logins()
            
            assert user.failed_login_attempts == 0
            assert user.account_locked_until is None
