"""
Integration tests for the test voter generator functionality.

These tests verify that:
1. The test voter generator creates valid data
2. The database initialization properly creates test voters
3. The helper script works correctly
4. Test voters can be used for authentication and voting
5. The system handles large numbers of test voters properly
"""

import pytest
import os
import tempfile
import subprocess
import json
from unittest.mock import patch
from app import create_app, db
from app.models import User, Role, Region, ElectoralRoll
from app.generate_test_voters import get_test_voters, get_test_voter_count, TEST_VOTERS
from app.init_db import init_database


class TestVoterGenerator:
    """Test the test voter data generator itself."""

    def test_generates_correct_number_of_voters(self):
        """Test that exactly 100 test voters are generated."""
        voters = get_test_voters()
        assert len(voters) == 100
        assert get_test_voter_count() == 100

    def test_voter_data_structure(self):
        """Test that each voter has all required fields."""
        voters = get_test_voters()
        required_fields = [
            'username', 'email', 'password', 'full_name', 'date_of_birth',
            'address_line1', 'suburb', 'state', 'postcode',
            'driver_license_number', 'roll_number'
        ]
        
        for voter in voters:
            for field in required_fields:
                assert field in voter, f"Missing field {field} in voter data"
                assert voter[field] is not None, f"Field {field} is None"
                assert str(voter[field]).strip(), f"Field {field} is empty"

    def test_unique_usernames(self):
        """Test that all usernames are unique."""
        voters = get_test_voters()
        usernames = [voter['username'] for voter in voters]
        assert len(usernames) == len(set(usernames)), "Duplicate usernames found"

    def test_unique_emails(self):
        """Test that all emails are unique."""
        voters = get_test_voters()
        emails = [voter['email'] for voter in voters]
        assert len(emails) == len(set(emails)), "Duplicate emails found"

    def test_unique_driver_licenses(self):
        """Test that all driver's license numbers are unique."""
        voters = get_test_voters()
        dl_numbers = [voter['driver_license_number'] for voter in voters]
        assert len(dl_numbers) == len(set(dl_numbers)), "Duplicate driver's license numbers found"

    def test_unique_roll_numbers(self):
        """Test that all electoral roll numbers are unique."""
        voters = get_test_voters()
        roll_numbers = [voter['roll_number'] for voter in voters]
        assert len(roll_numbers) == len(set(roll_numbers)), "Duplicate roll numbers found"

    def test_username_format(self):
        """Test that usernames follow the expected format."""
        voters = get_test_voters()
        for i, voter in enumerate(voters):
            expected_username = f"testvoter{i+1:03d}"
            assert voter['username'] == expected_username, f"Username format incorrect: {voter['username']}"

    def test_email_format(self):
        """Test that emails have the correct domain."""
        voters = get_test_voters()
        for voter in voters:
            assert voter['email'].endswith('@testvoters.com'), f"Email domain incorrect: {voter['email']}"

    def test_password_consistency(self):
        """Test that all test voters have the same password."""
        voters = get_test_voters()
        for voter in voters:
            assert voter['password'] == 'testpass123', "Test voter password is not consistent"

    def test_roll_number_format(self):
        """Test that roll numbers follow the expected format."""
        voters = get_test_voters()
        for i, voter in enumerate(voters):
            expected_roll = f"ER-{1000 + i + 1:04d}"
            assert voter['roll_number'] == expected_roll, f"Roll number format incorrect: {voter['roll_number']}"

    def test_valid_australian_locations(self):
        """Test that all addresses use valid Australian locations."""
        voters = get_test_voters()
        valid_states = ['NSW', 'VIC', 'QLD', 'WA', 'SA', 'ACT', 'NT', 'TAS']
        
        for voter in voters:
            assert voter['state'] in valid_states, f"Invalid state: {voter['state']}"
            assert len(voter['postcode']) == 4, f"Invalid postcode length: {voter['postcode']}"
            assert voter['postcode'].isdigit(), f"Postcode should be numeric: {voter['postcode']}"


class TestDatabaseIntegration:
    """Test the integration with the database initialization."""

    @pytest.fixture
    def test_app(self):
        """Create a test app with temporary database."""
        db_fd, db_path = tempfile.mkstemp()
        
        app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
            'SECRET_KEY': 'test-secret-key',
            'WTF_CSRF_ENABLED': False,
        })

        with app.app_context():
            yield app

        # Cleanup
        import time
        for _ in range(5):
            try:
                os.close(db_fd)
                os.unlink(db_path)
                break
            except OSError:
                time.sleep(0.1)

    def test_database_initialization_without_test_voters(self, test_app):
        """Test that database initialization works without test voters."""
        with test_app.app_context():
            # Mock environment variable to disable test voters
            with patch.dict(os.environ, {'CREATE_TEST_VOTERS': 'false'}):
                init_database(test_app)
                
                # Should have basic users but no test voters
                total_users = User.query.count()
                test_voters = User.query.filter(User.username.like('testvoter%')).count()
                
                assert total_users >= 4, "Should have at least basic users (admin, delegate1, voter1, lix)"
                assert test_voters == 0, "Should not have any test voters"

    def test_database_initialization_with_test_voters(self, test_app):
        """Test that database initialization creates test voters when enabled."""
        with test_app.app_context():
            # Mock environment variable to enable test voters
            with patch.dict(os.environ, {'CREATE_TEST_VOTERS': 'true'}):
                init_database(test_app)
                
                # Should have basic users plus 100 test voters
                total_users = User.query.count()
                test_voters = User.query.filter(User.username.like('testvoter%')).count()
                
                assert total_users >= 104, "Should have basic users + 100 test voters"
                assert test_voters == 100, "Should have exactly 100 test voters"

    def test_test_voters_have_correct_role(self, test_app):
        """Test that test voters are assigned the voter role."""
        with test_app.app_context():
            with patch.dict(os.environ, {'CREATE_TEST_VOTERS': 'true'}):
                init_database(test_app)
                
                voter_role = Role.query.filter_by(name='voter').first()
                test_voters = User.query.filter(User.username.like('testvoter%')).all()
                
                for user in test_voters:
                    assert user.role_id == voter_role.id, f"Test voter {user.username} has wrong role"

    def test_test_voters_have_electoral_roll_entries(self, test_app):
        """Test that test voters get electoral roll entries."""
        with test_app.app_context():
            with patch.dict(os.environ, {'CREATE_TEST_VOTERS': 'true'}):
                init_database(test_app)
                
                test_users = User.query.filter(User.username.like('testvoter%')).all()
                
                for user in test_users:
                    roll_entry = ElectoralRoll.query.filter_by(user_id=user.id).first()
                    assert roll_entry is not None, f"Test voter {user.username} missing electoral roll entry"
                    assert roll_entry.status == 'active', f"Test voter {user.username} not active"
                    assert roll_entry.verified is True, f"Test voter {user.username} not verified"

    def test_test_voters_can_authenticate(self, test_app):
        """Test that test voters can authenticate with their passwords."""
        with test_app.app_context():
            with patch.dict(os.environ, {'CREATE_TEST_VOTERS': 'true'}):
                init_database(test_app)
                
                # Test a few random test voters
                test_usernames = ['testvoter001', 'testvoter050', 'testvoter100']
                
                for username in test_usernames:
                    user = User.query.filter_by(username=username).first()
                    assert user is not None, f"Test voter {username} not found"
                    assert user.check_password('testpass123'), f"Password check failed for {username}"

    def test_duplicate_initialization_idempotent(self, test_app):
        """Test that running initialization twice doesn't create duplicates."""
        with test_app.app_context():
            with patch.dict(os.environ, {'CREATE_TEST_VOTERS': 'true'}):
                # Initialize twice
                init_database(test_app)
                first_count = User.query.count()
                
                init_database(test_app)
                second_count = User.query.count()
                
                assert first_count == second_count, "Database initialization should be idempotent"


class TestHelperScript:
    """Test the helper script functionality."""

    def setup_method(self):
        """Setup for each test method."""
        self.original_env = os.environ.get('CREATE_TEST_VOTERS')

    def teardown_method(self):
        """Cleanup after each test method."""
        if self.original_env is not None:
            os.environ['CREATE_TEST_VOTERS'] = self.original_env
        elif 'CREATE_TEST_VOTERS' in os.environ:
            del os.environ['CREATE_TEST_VOTERS']

    def test_helper_script_show_command(self):
        """Test that the helper script shows current status."""
        result = subprocess.run(
            ['python', 'create_test_voters.py', '--show'],
            cwd='/Users/zaynsmacantosh/sec-soft-sys-a3',
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert 'Current test voter creation status:' in result.stdout
        assert 'Available test voters: 100' in result.stdout

    def test_helper_script_enable_command(self):
        """Test that the helper script can enable test voters."""
        # Ensure we start with disabled state
        with patch.dict(os.environ, {'CREATE_TEST_VOTERS': 'false'}):
            result = subprocess.run(
                ['python', 'create_test_voters.py', '--enable'],
                cwd='/Users/zaynsmacantosh/sec-soft-sys-a3',
                capture_output=True,
                text=True
            )
            
            assert result.returncode == 0, f"Script failed: {result.stderr}"
            assert 'Test voter creation enabled' in result.stdout

    def test_helper_script_disable_command(self):
        """Test that the helper script can disable test voters."""
        result = subprocess.run(
            ['python', 'create_test_voters.py', '--disable'],
            cwd='/Users/zaynsmacantosh/sec-soft-sys-a3',
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert 'Test voter creation disabled' in result.stdout

    def test_helper_script_help(self):
        """Test that the helper script shows help when called without arguments."""
        result = subprocess.run(
            ['python', 'create_test_voters.py'],
            cwd='/Users/zaynsmacantosh/sec-soft-sys-a3',
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0
        assert 'usage:' in result.stdout.lower() or 'examples:' in result.stdout.lower()


class TestPerformanceAndScale:
    """Test performance and scale aspects of test voter generation."""

    def test_voter_generation_performance(self):
        """Test that voter generation completes in reasonable time."""
        import time
        
        start_time = time.time()
        voters = get_test_voters()
        end_time = time.time()
        
        generation_time = end_time - start_time
        assert generation_time < 1.0, f"Voter generation took too long: {generation_time:.2f}s"
        assert len(voters) == 100

    def test_database_insertion_performance(self):
        """Test that inserting test voters doesn't take too long."""
        db_fd, db_path = tempfile.mkstemp()
        
        app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
            'SECRET_KEY': 'test-secret-key',
        })

        try:
            with app.app_context():
                import time
                
                start_time = time.time()
                with patch.dict(os.environ, {'CREATE_TEST_VOTERS': 'true'}):
                    init_database(app)
                end_time = time.time()
                
                initialization_time = end_time - start_time
                assert initialization_time < 10.0, f"Database initialization too slow: {initialization_time:.2f}s"
                
                # Verify all users were created
                total_users = User.query.count()
                assert total_users >= 104, "Not all users were created"
        
        finally:
            # Cleanup
            import time
            for _ in range(5):
                try:
                    os.close(db_fd)
                    os.unlink(db_path)
                    break
                except OSError:
                    time.sleep(0.1)


class TestEndToEndWorkflow:
    """Test complete end-to-end workflows with test voters."""

    @pytest.fixture
    def app_with_test_voters(self):
        """Create an app with test voters enabled."""
        db_fd, db_path = tempfile.mkstemp()
        
        app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
            'SECRET_KEY': 'test-secret-key',
            'WTF_CSRF_ENABLED': False,
        })

        with app.app_context():
            with patch.dict(os.environ, {'CREATE_TEST_VOTERS': 'true'}):
                init_database(app)
            yield app

        # Cleanup
        import time
        for _ in range(5):
            try:
                os.close(db_fd)
                os.unlink(db_path)
                break
            except OSError:
                time.sleep(0.1)

    def test_test_voter_login_workflow(self, app_with_test_voters):
        """Test that test voters can log in through the web interface."""
        client = app_with_test_voters.test_client()
        
        # Test logging in as a test voter
        response = client.post('/login', data={
            'username': 'testvoter001',
            'password': 'testpass123'
        }, follow_redirects=True)
        
        assert response.status_code == 200
        # Should be redirected to dashboard after successful login
        assert b'dashboard' in response.data.lower() or b'vote' in response.data.lower()

    def test_multiple_test_voters_login(self, app_with_test_voters):
        """Test that multiple test voters can log in."""
        client = app_with_test_voters.test_client()
        
        test_usernames = ['testvoter001', 'testvoter025', 'testvoter050', 'testvoter075', 'testvoter100']
        
        for username in test_usernames:
            response = client.post('/login', data={
                'username': username,
                'password': 'testpass123'
            })
            
            # Should get redirect response (302) for successful login
            assert response.status_code == 302, f"Login failed for {username}"
            
            # Logout for next test
            client.get('/logout')

    def test_test_voter_data_integrity(self, app_with_test_voters):
        """Test that test voter data maintains integrity in the database."""
        with app_with_test_voters.app_context():
            # Get first test voter
            test_voter = User.query.filter_by(username='testvoter001').first()
            assert test_voter is not None
            
            # Check electoral roll entry
            roll_entry = ElectoralRoll.query.filter_by(user_id=test_voter.id).first()
            assert roll_entry is not None
            assert roll_entry.full_name == test_voter.username.replace('testvoter001', '').strip() or len(roll_entry.full_name) > 0
            
            # Check role assignment
            assert test_voter.role.name == 'voter'


if __name__ == '__main__':
    # Run tests when executed directly
    pytest.main([__file__, '-v'])