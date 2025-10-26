#!/usr/bin/env python3
"""
Flask Test Client Security Tests for Pagination
Using Flask's test client to bypass external security mechanisms while testing core pagination logic.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import User, Role
from flask import url_for
import pytest

def create_test_app():
    """Create test Flask app with testing configuration."""
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['LOGIN_DISABLED'] = False
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['ENABLE_MFA'] = False  # Disable MFA for testing
    return app

def test_pagination_security():
    """Test pagination security using Flask test client."""
    
    print("🧪 Pagination Security Test (Flask Client)")
    print("=" * 60)
    
    app = create_test_app()
    
    with app.app_context():
        with app.test_client() as client:
            
            # Test 1: Get admin user
            print("1️⃣ Getting admin user...")
            admin_user = User.query.filter_by(username='admin').first()
            if not admin_user:
                print("❌ Admin user not found")
                return False
            
            print(f"✅ Found admin user: {admin_user.username}")
            
            # Test 2: Login with test client
            print("2️⃣ Logging in as admin...")
            
            with client.session_transaction() as sess:
                # Simulate logged in user
                sess['_user_id'] = str(admin_user.id)
                sess['_fresh'] = True
            
            # Test 3: Test normal pagination
            print("3️⃣ Testing normal pagination (per_page=20)...")
            response = client.get('/admin/users?category=all&per_page=20')
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                print("✅ Normal pagination works")
                # Count users in response
                data = response.get_data(as_text=True)
                user_count = data.count('<tr>') - 1  # Subtract header row
                print(f"   Users displayed: {user_count}")
            else:
                print(f"❌ Normal pagination failed: {response.status_code}")
                return False
            
            # Test 4: Test maximum limit (per_page=40)
            print("4️⃣ Testing maximum limit (per_page=40)...")
            response = client.get('/admin/users?category=all&per_page=40')
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                print("✅ Maximum limit works")
                data = response.get_data(as_text=True)
                user_count = data.count('<tr>') - 1
                print(f"   Users displayed: {user_count}")
                if user_count <= 40:
                    print("✅ User count within limit")
                else:
                    print(f"❌ Too many users displayed: {user_count} > 40")
                    return False
            else:
                print(f"❌ Maximum limit test failed: {response.status_code}")
                return False
            
            # Test 5: Test bypass attempt (per_page=50)
            print("5️⃣ Testing bypass attempt (per_page=50)...")
            response = client.get('/admin/users?category=all&per_page=50')
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.get_data(as_text=True)
                user_count = data.count('<tr>') - 1
                print(f"   Users displayed: {user_count}")
                if user_count <= 40:
                    print("✅ Bypass blocked - limit enforced")
                else:
                    print(f"❌ SECURITY ISSUE: Bypass successful, {user_count} users shown")
                    return False
            else:
                print(f"❌ Bypass test failed: {response.status_code}")
                return False
            
            # Test 6: Test extreme bypass (per_page=99999)
            print("6️⃣ Testing extreme bypass (per_page=99999)...")
            response = client.get('/admin/users?category=all&per_page=99999')
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.get_data(as_text=True)
                user_count = data.count('<tr>') - 1
                print(f"   Users displayed: {user_count}")
                if user_count <= 40:
                    print("✅ Extreme bypass blocked - limit enforced")
                else:
                    print(f"❌ CRITICAL SECURITY ISSUE: Extreme bypass successful, {user_count} users shown")
                    return False
            else:
                print(f"❌ Extreme bypass test failed: {response.status_code}")
                return False
                
            # Test 7: Test invalid inputs
            print("7️⃣ Testing invalid inputs...")
            test_cases = [
                ('abc', 'Invalid string'),
                ('-5', 'Negative number'),
                ('0', 'Zero'),
                ('', 'Empty string'),
            ]
            
            for per_page_val, description in test_cases:
                print(f"   Testing {description}: per_page={per_page_val}")
                response = client.get(f'/admin/users?category=all&per_page={per_page_val}')
                
                if response.status_code == 200:
                    data = response.get_data(as_text=True)
                    user_count = data.count('<tr>') - 1
                    print(f"     Status: {response.status_code}, Users: {user_count}")
                    if user_count <= 40:
                        print(f"     ✅ {description} handled safely")
                    else:
                        print(f"     ❌ {description} allowed too many results: {user_count}")
                        return False
                else:
                    print(f"     ✅ {description} rejected (status {response.status_code})")
            
            print("\n" + "=" * 60)
            print("🎉 ALL PAGINATION SECURITY TESTS PASSED!")
            print("✅ Maximum limit of 40 users enforced in all scenarios")
            print("✅ Bypass attempts blocked successfully")
            print("✅ Invalid inputs handled safely")
            return True

def test_get_safe_page_limit_function():
    """Test the get_safe_page_limit function directly."""
    print("\n🔬 Testing get_safe_page_limit Function Directly")
    print("=" * 60)
    
    app = create_test_app()
    
    with app.app_context():
        from app.routes.admin_users import get_safe_page_limit
        
        test_cases = [
            (10, 10, "Normal case"),
            (40, 40, "Maximum allowed"),
            (50, 40, "Above maximum"),
            (99999, 40, "Extreme value"),
            (-5, 10, "Negative value"),
            (0, 10, "Zero value"),
            ("abc", 10, "String input"),
            ("", 10, "Empty string"),
            (None, 10, "None input"),
        ]
        
        for input_val, expected, description in test_cases:
            try:
                result = get_safe_page_limit(input_val)
                if result == expected:
                    print(f"✅ {description}: {input_val} -> {result}")
                else:
                    print(f"❌ {description}: {input_val} -> {result}, expected {expected}")
                    return False
            except Exception as e:
                print(f"❌ {description}: {input_val} -> Exception: {e}")
                return False
        
        print("✅ All get_safe_page_limit tests passed!")
        return True

if __name__ == "__main__":
    success = True
    
    # Run pagination security tests
    if not test_pagination_security():
        success = False
    
    # Run function tests
    if not test_get_safe_page_limit_function():
        success = False
    
    if success:
        print("\n🎊 ALL TESTS PASSED - PAGINATION SECURITY VALIDATED!")
        sys.exit(0)
    else:
        print("\n💥 SOME TESTS FAILED - SECURITY ISSUES DETECTED!")
        sys.exit(1)