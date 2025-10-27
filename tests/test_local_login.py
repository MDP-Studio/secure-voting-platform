#!/usr/bin/env python3
"""
Minimal test to debug login issue - can be run locally without Docker.
Run: python test_local_login.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import User, Role
import logging

logging.basicConfig(level=logging.DEBUG)

def test_local_login():
    """Test login with local Flask test client."""
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,
        'SECRET_KEY': 'test-secret-key',
        'ENABLE_MFA': False,
    })
    
    with app.app_context():
        # Create database
        db.create_all()
        
        # Create roles and users
        manager_role = Role(name='manager', description='System admin')
        voter_role = Role(name='voter', description='Regular voter')
        db.session.add_all([manager_role, voter_role])
        db.session.commit()
        
        # Create admin user
        admin = User(
            username='admin',
            email='admin@test.com',
            driver_lic_no='ADMIN001',
            driver_lic_state='VIC',
            role=manager_role
        )
        admin.set_password('Admin@123456!')
        db.session.add(admin)
        db.session.commit()
        
        # Test login
        client = app.test_client()
        
        print("\n" + "="*80)
        print("Test 1: Load login page")
        print("="*80)
        response = client.get('/login')
        print(f"Status: {response.status_code}")
        assert response.status_code == 200, "Login page should load"
        
        print("\n" + "="*80)
        print("Test 2: Login with correct credentials")
        print("="*80)
        response = client.post('/login', data={
            'username': 'admin',
            'password': 'Admin@123456!'
        }, follow_redirects=False)
        print(f"Status: {response.status_code}")
        print(f"Location: {response.headers.get('Location', 'N/A')}")
        print(f"Set-Cookie: {response.headers.get('Set-Cookie', 'N/A')}")
        assert response.status_code == 302, f"Login should redirect, got {response.status_code}"
        assert '/dashboard' in response.headers.get('Location', ''), "Should redirect to dashboard"
        
        print("\n" + "="*80)
        print("Test 3: Access dashboard after login (with follow_redirects)")
        print("="*80)
        response = client.get('/dashboard', follow_redirects=True)
        print(f"Status: {response.status_code}")
        print(f"'welcome' in response: {'welcome' in response.text.lower()}")
        print(f"'login' in response: {'login' in response.text.lower()}")
        if 'welcome' not in response.text.lower():
            print(f"Response first 300 chars: {response.text[:300]}")
        assert response.status_code == 200, "Dashboard should return 200"
        assert 'welcome' in response.text.lower() or 'dashboard' in response.text.lower(), "Dashboard should show welcome message"
        
        print("\n" + "="*80)
        print("All tests passed!")
        print("="*80)

if __name__ == '__main__':
    test_local_login()
