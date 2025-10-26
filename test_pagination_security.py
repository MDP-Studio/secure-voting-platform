"""
Test pagination security for admin routes.

Tests that:
1. Page limits above 40 are blocked and return only 40 records
2. Invalid pagination parameters are handled safely
3. Security logging works for attack attempts
4. Normal pagination works correctly within limits
"""

import pytest
import logging
from flask import url_for
from app import create_app, db
from app.models import User, Role
from app.routes.admin_users import get_safe_page_limit


class TestPaginationSecurity:
    """Test cases for pagination security features."""
    
    @pytest.fixture
    def app(self):
        """Create test application."""
        app = create_app()
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        app.config['WTF_CSRF_ENABLED'] = False
        return app
    
    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return app.test_client()
    
    @pytest.fixture
    def setup_test_data(self, app):
        """Set up test database with users."""
        with app.app_context():
            db.create_all()
            
            # Create roles (check if they exist first)
            admin_role = Role.query.filter_by(name='manager').first()
            if not admin_role:
                admin_role = Role(name='manager', description='Administrator')
                db.session.add(admin_role)
            
            voter_role = Role.query.filter_by(name='voter').first()
            if not voter_role:
                voter_role = Role(name='voter', description='Voter')
                db.session.add(voter_role)
            
            db.session.flush()
            
            # Create admin user
            admin_user = User(
                username='admin',
                email='admin@test.com',
                role=admin_role,
                account_status='approved',
                driver_lic_no='ADM123456789',
                driver_lic_state='NSW'
            )
            admin_user.set_password('AdminPassword123!')
            db.session.add(admin_user)
            
            # Create 50 test users (more than the 40 limit)
            for i in range(1, 51):
                user = User(
                    username=f'testuser{i:03d}',
                    email=f'test{i:03d}@example.com',
                    role=voter_role,
                    account_status='approved',
                    driver_lic_no=f'TST{i:06d}12X',
                    driver_lic_state='VIC'
                )
                user.set_password('TestPassword123!')
                db.session.add(user)
            
            db.session.commit()
            yield
            # Clean up after test
            db.session.rollback()
            db.session.remove()
            db.drop_all()
    
    def login_as_admin(self, client):
        """Helper to log in as admin."""
        return client.post('/login', data={
            'username': 'admin',
            'password': 'AdminPassword123!'
        }, follow_redirects=True)

    def test_get_safe_page_limit_function_unit_tests(self, app, client):
        """Unit tests for the get_safe_page_limit function."""
        
        with app.test_request_context('/?per_page=test'):
            # Test normal valid values
            assert get_safe_page_limit('10') == 10
            assert get_safe_page_limit('20') == 20
            assert get_safe_page_limit('40') == 40
            
            # Test edge cases
            assert get_safe_page_limit('1') == 1  # Minimum valid
            assert get_safe_page_limit('0') == 10  # Invalid zero
            assert get_safe_page_limit('-5') == 10  # Invalid negative
            
            # Test security boundary (CRITICAL TEST)
            assert get_safe_page_limit('41') == 40  # Just above limit
            assert get_safe_page_limit('100') == 40  # Well above limit
            assert get_safe_page_limit('999999') == 40  # Attack attempt
            
            # Test invalid inputs
            assert get_safe_page_limit('abc') == 20  # Invalid string
            assert get_safe_page_limit('') == 20  # Empty string
            assert get_safe_page_limit(None) == 20  # None value
            assert get_safe_page_limit('10.5') == 20  # Float string
            
            # Test with custom max_limit (should still respect absolute max)
            assert get_safe_page_limit('25', max_limit=30) == 25  # Within both limits
            assert get_safe_page_limit('50', max_limit=30) == 40  # Absolute max wins over all
            assert get_safe_page_limit('50', max_limit=50) == 40  # Absolute max wins
    
    def test_pagination_security_via_url_parameters(self, app, client, setup_test_data):
        """Integration test: Verify pagination security via URL manipulation."""
        
        with app.app_context():
            # Login as admin
            self.login_as_admin(client)
            
            # Test normal pagination (should work)
            response = client.get('/admin/users?per_page=20')
            assert response.status_code == 200
            assert b'testuser001' in response.data  # Should show users
            
            # Test maximum allowed limit (should work)
            response = client.get('/admin/users?per_page=40')
            assert response.status_code == 200
            assert b'testuser001' in response.data
            
            # CRITICAL SECURITY TEST: Attempt to bypass limit
            response = client.get('/admin/users?per_page=50')
            assert response.status_code == 200
            # Should still return results but limited to 40
            assert b'testuser001' in response.data
            
            # Extreme attack attempt
            response = client.get('/admin/users?per_page=99999')
            assert response.status_code == 200
            # Should not crash and should limit results
            assert b'testuser001' in response.data
            
            # Invalid parameters
            response = client.get('/admin/users?per_page=abc')
            assert response.status_code == 200
            
            response = client.get('/admin/users?per_page=-10')
            assert response.status_code == 200
    
    def test_pagination_response_content_limits(self, app, client, setup_test_data):
        """Test that responses actually contain limited number of records."""
        
        with app.app_context():
            # Login as admin
            self.login_as_admin(client)
            
            # Request 10 per page - should see exactly 10 users in response
            response = client.get('/admin/users?per_page=10')
            response_text = response.data.decode('utf-8')
            
            # Count user rows (look for testuser pattern)
            user_count = response_text.count('testuser')
            assert user_count == 10, f"Expected 10 users, found {user_count}"
            
            # Request 40 per page - should see exactly 40 users
            response = client.get('/admin/users?per_page=40')
            response_text = response.data.decode('utf-8')
            user_count = response_text.count('testuser')
            assert user_count == 40, f"Expected 40 users, found {user_count}"
            
            # CRITICAL TEST: Request 50 per page - should still only see 40 users
            response = client.get('/admin/users?per_page=50')
            response_text = response.data.decode('utf-8')
            user_count = response_text.count('testuser')
            assert user_count == 40, f"SECURITY BREACH: Expected 40 users max, found {user_count}"
            
            # Extreme attack: Request 99999 per page - should still only see 40 users
            response = client.get('/admin/users?per_page=99999')
            response_text = response.data.decode('utf-8')
            user_count = response_text.count('testuser')
            assert user_count == 40, f"SECURITY BREACH: Expected 40 users max, found {user_count}"
    
    def test_pagination_with_different_pages(self, app, client, setup_test_data):
        """Test pagination across multiple pages maintains security."""
        
        with app.app_context():
            # Login as admin
            self.login_as_admin(client)
            
            # Page 1 with max limit
            response = client.get('/admin/users?page=1&per_page=40')
            assert response.status_code == 200
            response_text = response.data.decode('utf-8')
            user_count = response_text.count('testuser')
            assert user_count == 40
            
            # Page 2 should have remaining users (10 + admin = 11 total remaining)
            response = client.get('/admin/users?page=2&per_page=40')
            assert response.status_code == 200
            response_text = response.data.decode('utf-8')
            user_count = response_text.count('testuser')
            # Should show remaining test users (50 total - 40 from page 1 = 10)
            assert user_count == 10, f"Expected 10 users on page 2, found {user_count}"
            
            # Test security on page 2: attempt excessive limit
            response = client.get('/admin/users?page=2&per_page=99999')
            assert response.status_code == 200
            response_text = response.data.decode('utf-8')
            user_count = response_text.count('testuser')
            # Should still only show the remaining users, not more than available
            assert user_count <= 40, f"SECURITY BREACH: Too many users on page 2: {user_count}"
    
    def test_security_logging(self, app, client, setup_test_data, caplog):
        """Test that security violations are logged."""
        
        with app.app_context():
            # Set up logging capture
            with caplog.at_level(logging.WARNING):
                # Login as admin
                self.login_as_admin(client)
                
                # Attempt to exceed pagination limit (should trigger security log)
                response = client.get('/admin/users?per_page=100')
                assert response.status_code == 200
                
                # Check that security warning was logged
                security_logs = [record for record in caplog.records 
                               if 'SECURITY' in record.message and 'attempted to request' in record.message]
                
                assert len(security_logs) > 0, "Security violation should be logged"
                assert '100 records' in security_logs[0].message
                assert 'exceeds maximum 40' in security_logs[0].message
    
    def test_form_submission_security(self, app, client, setup_test_data):
        """Test security when form is submitted with malicious values."""
        
        with app.app_context():
            # Login as admin
            self.login_as_admin(client)
            
            # Submit form with normal values
            response = client.get('/admin/users', query_string={
                'category': 'all',
                'per_page': '20'
            })
            assert response.status_code == 200
            
            # Submit form with malicious per_page value
            response = client.get('/admin/users', query_string={
                'category': 'all',
                'per_page': '999999'  # Attack attempt
            })
            assert response.status_code == 200
            
            # Submit form with invalid per_page value
            response = client.get('/admin/users', query_string={
                'category': 'all',
                'per_page': 'DROP TABLE users'  # SQL injection attempt
            })
            assert response.status_code == 200
    
    def test_unauthorized_access_pagination(self, app, client, setup_test_data):
        """Test that pagination security applies even without proper authentication."""
        
        with app.app_context():
            # Don't login - should redirect to login page
            response = client.get('/admin/users?per_page=99999')
            assert response.status_code == 302  # Should redirect
            
            # Follow redirect should go to login
            response = client.get('/admin/users?per_page=99999', follow_redirects=True)
            assert b'login' in response.data.lower() or b'sign in' in response.data.lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])