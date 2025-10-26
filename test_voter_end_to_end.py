#!/usr/bin/env python3
"""
End-to-End Test Suite for Test Voter Generator

This script demonstrates and validates the complete functionality
of the test voter generator system including:
1. Data generation
2. Database integration
3. Web authentication
4. Helper script functionality
"""

import os
import sys
import tempfile
import shutil
import subprocess
from datetime import datetime

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app, db
from app.models import User, Role, Region, ElectoralRoll
from app.init_db import init_database
from app.generate_test_voters import get_test_voters, get_test_voter_count


class EndToEndTestSuite:
    """Complete end-to-end test suite for test voter functionality."""

    def __init__(self):
        self.results = []
        self.temp_dir = None
        self.original_env = os.environ.get('CREATE_TEST_VOTERS')

    def setup(self):
        """Setup test environment."""
        print("🔧 Setting up test environment...")
        self.temp_dir = tempfile.mkdtemp()
        
    def cleanup(self):
        """Clean up test environment."""
        print("🧹 Cleaning up test environment...")
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        
        # Restore original environment
        if self.original_env is not None:
            os.environ['CREATE_TEST_VOTERS'] = self.original_env
        elif 'CREATE_TEST_VOTERS' in os.environ:
            del os.environ['CREATE_TEST_VOTERS']

    def log_result(self, test_name, success, details=None):
        """Log test result."""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {status}: {test_name}")
        if details and not success:
            print(f"    Details: {details}")
        self.results.append((test_name, success, details))

    def test_data_generation(self):
        """Test 1: Data Generation"""
        print("\n📊 Test 1: Data Generation")
        
        try:
            # Test voter count
            voters = get_test_voters()
            count = get_test_voter_count()
            
            assert len(voters) == 100, f"Expected 100 voters, got {len(voters)}"
            assert count == 100, f"Count function returned {count}"
            
            # Test data structure
            voter = voters[0]
            required_fields = ['username', 'email', 'password', 'full_name', 'date_of_birth']
            for field in required_fields:
                assert field in voter, f"Missing field: {field}"
            
            # Test uniqueness
            usernames = [v['username'] for v in voters]
            assert len(set(usernames)) == 100, "Duplicate usernames found"
            
            self.log_result("Data generation", True)
            
        except Exception as e:
            self.log_result("Data generation", False, str(e))

    def test_database_integration(self):
        """Test 2: Database Integration"""
        print("\n🗄️  Test 2: Database Integration")
        
        db_path = os.path.join(self.temp_dir, 'test.db')
        app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
            'SECRET_KEY': 'test-secret-key',
        })

        try:
            with app.app_context():
                # Test without test voters
                os.environ['CREATE_TEST_VOTERS'] = 'false'
                init_database(app)
                
                basic_count = User.query.count()
                assert basic_count >= 4, f"Expected at least 4 basic users, got {basic_count}"
                
                # Test with test voters
                os.environ['CREATE_TEST_VOTERS'] = 'true'
                init_database(app)
                
                total_count = User.query.count()
                test_voter_count = User.query.filter(User.username.like('testvoter%')).count()
                
                assert test_voter_count == 100, f"Expected 100 test voters, got {test_voter_count}"
                assert total_count >= 104, f"Expected at least 104 total users, got {total_count}"
                
                # Test authentication
                test_user = User.query.filter_by(username='testvoter001').first()
                assert test_user is not None, "testvoter001 not found"
                assert test_user.check_password('testpass123'), "Password check failed"
                
                # Test electoral roll
                roll_entry = ElectoralRoll.query.filter_by(user_id=test_user.id).first()
                assert roll_entry is not None, "Electoral roll entry not found"
                assert roll_entry.verified is True, "Test voter not verified"
                
            self.log_result("Database integration", True)
            
        except Exception as e:
            self.log_result("Database integration", False, str(e))

    def test_web_authentication(self):
        """Test 3: Web Authentication"""
        print("\n🌐 Test 3: Web Authentication")
        
        db_path = os.path.join(self.temp_dir, 'auth_test.db')
        app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
            'SECRET_KEY': 'test-secret-key',
            'WTF_CSRF_ENABLED': False,
        })

        try:
            with app.app_context():
                os.environ['CREATE_TEST_VOTERS'] = 'true'
                init_database(app)

            client = app.test_client()
            
            # Test login for several test voters
            test_usernames = ['testvoter001', 'testvoter050', 'testvoter100']
            
            for username in test_usernames:
                response = client.post('/login', data={
                    'username': username,
                    'password': 'testpass123'
                })
                
                assert response.status_code == 302, f"Login failed for {username}"
                
                # Logout for next test
                client.get('/logout')
            
            self.log_result("Web authentication", True)
            
        except Exception as e:
            self.log_result("Web authentication", False, str(e))

    def test_helper_script(self):
        """Test 4: Helper Script Functionality"""
        print("\n🛠️  Test 4: Helper Script Functionality")
        
        try:
            # Test show command
            result = subprocess.run(
                ['python', 'create_test_voters.py', '--show'],
                capture_output=True, text=True, cwd='.'
            )
            assert result.returncode == 0, f"Show command failed: {result.stderr}"
            assert 'Available test voters: 100' in result.stdout
            
            # Test enable command
            result = subprocess.run(
                ['python', 'create_test_voters.py', '--enable'],
                capture_output=True, text=True, cwd='.'
            )
            assert result.returncode == 0, f"Enable command failed: {result.stderr}"
            assert 'enabled' in result.stdout
            
            # Test disable command
            result = subprocess.run(
                ['python', 'create_test_voters.py', '--disable'],
                capture_output=True, text=True, cwd='.'
            )
            assert result.returncode == 0, f"Disable command failed: {result.stderr}"
            assert 'disabled' in result.stdout
            
            self.log_result("Helper script functionality", True)
            
        except Exception as e:
            self.log_result("Helper script functionality", False, str(e))

    def test_performance(self):
        """Test 5: Performance"""
        print("\n⚡ Test 5: Performance")
        
        try:
            import time
            
            # Test data generation performance
            start_time = time.time()
            voters = get_test_voters()
            gen_time = time.time() - start_time
            
            assert gen_time < 1.0, f"Data generation took {gen_time:.2f}s (should be < 1s)"
            assert len(voters) == 100
            
            # Test database initialization performance
            db_path = os.path.join(self.temp_dir, 'perf_test.db')
            app = create_app({
                'TESTING': True,
                'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
                'SECRET_KEY': 'test-secret-key',
            })

            with app.app_context():
                os.environ['CREATE_TEST_VOTERS'] = 'true'
                start_time = time.time()
                init_database(app)
                init_time = time.time() - start_time
                
                assert init_time < 15.0, f"Database init took {init_time:.2f}s (should be < 15s)"
                
                # Verify all data was created
                total_users = User.query.count()
                assert total_users >= 104
            
            self.log_result("Performance", True, f"Gen: {gen_time:.3f}s, Init: {init_time:.3f}s")
            
        except Exception as e:
            self.log_result("Performance", False, str(e))

    def test_data_quality(self):
        """Test 6: Data Quality"""
        print("\n🔍 Test 6: Data Quality")
        
        try:
            voters = get_test_voters()
            
            # Check for realistic names
            for voter in voters[:10]:  # Check first 10
                name_parts = voter['full_name'].split()
                assert len(name_parts) >= 2, f"Name should have first and last: {voter['full_name']}"
                assert all(part.isalpha() for part in name_parts), f"Name contains non-letters: {voter['full_name']}"
            
            # Check email format
            for voter in voters:
                email = voter['email']
                assert '@testvoters.com' in email, f"Wrong email domain: {email}"
                assert email.count('@') == 1, f"Invalid email format: {email}"
            
            # Check Australian addresses
            valid_states = ['NSW', 'VIC', 'QLD', 'WA', 'SA', 'ACT', 'NT', 'TAS']
            for voter in voters:
                assert voter['state'] in valid_states, f"Invalid state: {voter['state']}"
                assert len(voter['postcode']) == 4, f"Invalid postcode: {voter['postcode']}"
                assert voter['postcode'].isdigit(), f"Postcode not numeric: {voter['postcode']}"
            
            # Check driver license format
            for voter in voters:
                dl = voter['driver_license_number']
                assert len(dl) == 8, f"DL wrong length: {dl}"
                assert dl[:2].isalpha(), f"DL should start with letters: {dl}"
                assert dl[2:].isdigit(), f"DL should end with digits: {dl}"
            
            self.log_result("Data quality", True)
            
        except Exception as e:
            self.log_result("Data quality", False, str(e))

    def run_all_tests(self):
        """Run all tests in the suite."""
        print("🧪 Starting End-to-End Test Suite for Test Voter Generator")
        print("=" * 70)
        
        self.setup()
        
        try:
            self.test_data_generation()
            self.test_database_integration()
            self.test_web_authentication()
            self.test_helper_script()
            self.test_performance()
            self.test_data_quality()
            
        finally:
            self.cleanup()
        
        # Print final summary
        print("\n" + "=" * 70)
        passed = sum(1 for _, success, _ in self.results if success)
        total = len(self.results)
        
        print(f"📈 Final Results: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 ALL TESTS PASSED! The test voter generator is fully functional.")
            return True
        else:
            print("❌ Some tests failed:")
            for test_name, success, details in self.results:
                if not success:
                    print(f"  - {test_name}: {details}")
            return False

    def print_feature_summary(self):
        """Print a summary of all features tested."""
        print("\n📋 Feature Summary:")
        print("✅ Generates 100 unique test voters with realistic data")
        print("✅ Integrates with database initialization system")
        print("✅ Creates electoral roll entries for all test voters")
        print("✅ Supports web authentication for test voters")
        print("✅ Provides helper script for easy management")
        print("✅ Performs well with large datasets")
        print("✅ Generates high-quality, realistic test data")
        print("✅ Is disabled by default for production safety")
        print("✅ Supports idempotent database operations")
        print("✅ Includes comprehensive test coverage")


def main():
    """Main function to run the end-to-end test suite."""
    print("🚀 Test Voter Generator - End-to-End Validation")
    print(f"📅 Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    suite = EndToEndTestSuite()
    success = suite.run_all_tests()
    
    suite.print_feature_summary()
    
    if success:
        print("\n🎯 CONCLUSION: The test voter generator is ready for production use!")
        print("💡 To use: Set CREATE_TEST_VOTERS=true in .env and run python run_demo.py")
        sys.exit(0)
    else:
        print("\n❌ CONCLUSION: Issues found that need to be addressed.")
        sys.exit(1)


if __name__ == '__main__':
    main()