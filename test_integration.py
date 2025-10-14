#!/usr/bin/env python3
"""
Database Integration Test for Test Voter Generator

This script tests the complete integration of the test voter generator
with the database initialization system.
"""

import os
import sys
import tempfile
import shutil
from datetime import datetime

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app, db
from app.models import User, Role, Region, ElectoralRoll
from app.init_db import init_database


class DatabaseIntegrationTest:
    """Test database integration with test voters."""

    def __init__(self):
        self.test_results = []
        self.temp_dir = None

    def setup_test_environment(self):
        """Setup a temporary test environment."""
        self.temp_dir = tempfile.mkdtemp()
        db_path = os.path.join(self.temp_dir, 'test.db')
        
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
            'SECRET_KEY': 'test-secret-key',
            'WTF_CSRF_ENABLED': False,
        })

    def cleanup_test_environment(self):
        """Clean up the test environment."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def run_test(self, test_name, test_func):
        """Run a single test and record the result."""
        try:
            print(f"Running {test_name}...", end=' ')
            test_func()
            print("✅ PASSED")
            self.test_results.append((test_name, True, None))
        except Exception as e:
            print(f"❌ FAILED: {e}")
            self.test_results.append((test_name, False, str(e)))

    def test_database_init_without_test_voters(self):
        """Test database initialization without test voters."""
        with self.app.app_context():
            # Set environment to disable test voters
            os.environ['CREATE_TEST_VOTERS'] = 'false'
            
            try:
                init_database(self.app)
                
                # Check basic users exist
                total_users = User.query.count()
                test_voters = User.query.filter(User.username.like('testvoter%')).count()
                
                assert total_users >= 4, f"Expected at least 4 basic users, got {total_users}"
                assert test_voters == 0, f"Expected 0 test voters, got {test_voters}"
                
            finally:
                # Clean up environment
                if 'CREATE_TEST_VOTERS' in os.environ:
                    del os.environ['CREATE_TEST_VOTERS']

    def test_database_init_with_test_voters(self):
        """Test database initialization with test voters enabled."""
        with self.app.app_context():
            # Set environment to enable test voters
            os.environ['CREATE_TEST_VOTERS'] = 'true'
            
            try:
                init_database(self.app)
                
                # Check all users exist
                total_users = User.query.count()
                test_voters = User.query.filter(User.username.like('testvoter%')).count()
                basic_users = total_users - test_voters
                
                assert basic_users >= 4, f"Expected at least 4 basic users, got {basic_users}"
                assert test_voters == 100, f"Expected 100 test voters, got {test_voters}"
                assert total_users >= 104, f"Expected at least 104 total users, got {total_users}"
                
            finally:
                # Clean up environment
                if 'CREATE_TEST_VOTERS' in os.environ:
                    del os.environ['CREATE_TEST_VOTERS']

    def test_test_voters_have_correct_data(self):
        """Test that test voters have correct role and electoral roll data."""
        with self.app.app_context():
            os.environ['CREATE_TEST_VOTERS'] = 'true'
            
            try:
                init_database(self.app)
                
                # Get voter role
                voter_role = Role.query.filter_by(name='voter').first()
                assert voter_role is not None, "Voter role not found"
                
                # Check first few test voters
                test_usernames = ['testvoter001', 'testvoter002', 'testvoter003']
                
                for username in test_usernames:
                    user = User.query.filter_by(username=username).first()
                    assert user is not None, f"Test voter {username} not found"
                    assert user.role_id == voter_role.id, f"Test voter {username} has wrong role"
                    
                    # Check electoral roll entry
                    roll_entry = ElectoralRoll.query.filter_by(user_id=user.id).first()
                    assert roll_entry is not None, f"Electoral roll entry missing for {username}"
                    assert roll_entry.status == 'active', f"Test voter {username} not active"
                    assert roll_entry.verified is True, f"Test voter {username} not verified"
                
            finally:
                if 'CREATE_TEST_VOTERS' in os.environ:
                    del os.environ['CREATE_TEST_VOTERS']

    def test_test_voter_authentication(self):
        """Test that test voters can authenticate."""
        with self.app.app_context():
            os.environ['CREATE_TEST_VOTERS'] = 'true'
            
            try:
                init_database(self.app)
                
                # Test authentication for a few test voters
                test_usernames = ['testvoter001', 'testvoter050', 'testvoter100']
                
                for username in test_usernames:
                    user = User.query.filter_by(username=username).first()
                    assert user is not None, f"Test voter {username} not found"
                    assert user.check_password('testpass123'), f"Password check failed for {username}"
                
            finally:
                if 'CREATE_TEST_VOTERS' in os.environ:
                    del os.environ['CREATE_TEST_VOTERS']

    def test_idempotent_initialization(self):
        """Test that multiple initializations don't create duplicates."""
        with self.app.app_context():
            os.environ['CREATE_TEST_VOTERS'] = 'true'
            
            try:
                # Initialize database twice
                init_database(self.app)
                first_count = User.query.count()
                
                init_database(self.app)
                second_count = User.query.count()
                
                assert first_count == second_count, f"User count changed: {first_count} -> {second_count}"
                
                # Check for duplicate usernames
                usernames = [user.username for user in User.query.all()]
                unique_usernames = set(usernames)
                assert len(usernames) == len(unique_usernames), "Duplicate usernames found"
                
            finally:
                if 'CREATE_TEST_VOTERS' in os.environ:
                    del os.environ['CREATE_TEST_VOTERS']

    def test_performance(self):
        """Test that initialization completes in reasonable time."""
        with self.app.app_context():
            os.environ['CREATE_TEST_VOTERS'] = 'true'
            
            try:
                import time
                start_time = time.time()
                init_database(self.app)
                end_time = time.time()
                
                duration = end_time - start_time
                assert duration < 30.0, f"Initialization took too long: {duration:.2f}s"
                
            finally:
                if 'CREATE_TEST_VOTERS' in os.environ:
                    del os.environ['CREATE_TEST_VOTERS']

    def run_all_tests(self):
        """Run all integration tests."""
        print("🧪 Starting Database Integration Tests for Test Voter Generator")
        print("=" * 60)
        
        self.setup_test_environment()
        
        try:
            # Run all tests
            self.run_test("Database Init Without Test Voters", self.test_database_init_without_test_voters)
            self.run_test("Database Init With Test Voters", self.test_database_init_with_test_voters)
            self.run_test("Test Voters Data Validation", self.test_test_voters_have_correct_data)
            self.run_test("Test Voter Authentication", self.test_test_voter_authentication)
            self.run_test("Idempotent Initialization", self.test_idempotent_initialization)
            self.run_test("Performance Test", self.test_performance)
            
        finally:
            self.cleanup_test_environment()
        
        # Print summary
        print("\n" + "=" * 60)
        passed = sum(1 for _, success, _ in self.test_results if success)
        total = len(self.test_results)
        
        print(f"📊 Test Summary: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All tests passed!")
            return True
        else:
            print("❌ Some tests failed:")
            for test_name, success, error in self.test_results:
                if not success:
                    print(f"  - {test_name}: {error}")
            return False


def main():
    """Main function to run the integration tests."""
    tester = DatabaseIntegrationTest()
    success = tester.run_all_tests()
    
    if success:
        print("\n✅ All integration tests passed! The test voter generator is working correctly.")
        sys.exit(0)
    else:
        print("\n❌ Some integration tests failed. Please check the errors above.")
        sys.exit(1)


if __name__ == '__main__':
    main()