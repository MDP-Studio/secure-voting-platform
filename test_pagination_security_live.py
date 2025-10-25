"""
Simple integration test for pagination security.
Tests that page limits above 40 are blocked and return only 40 records max.
"""

import requests
import time


def test_pagination_security_live():
    """
    Live integration test that directly tests the running Flask app.
    
    CRITICAL SECURITY TEST: Verifies that pagination limits cannot be bypassed.
    """
    
    base_url = "http://127.0.0.1:5000"
    admin_credentials = {'username': 'admin', 'password': 'Admin@123456!'}
    
    print("🔐 Starting Pagination Security Test...")
    
    # Create a session to maintain login
    session = requests.Session()
    
    try:
        # Step 1: Login as admin
        print("1️⃣ Logging in as admin...")
        login_response = session.post(f"{base_url}/login", data=admin_credentials)
        
        if login_response.status_code != 200:
            print(f"❌ Login failed: {login_response.status_code}")
            return False
        
        print("✅ Login successful")
        
        # Step 2: Test normal pagination (should work)
        print("2️⃣ Testing normal pagination (20 per page)...")
        response = session.get(f"{base_url}/admin/users?per_page=20")
        
        if response.status_code != 200:
            print(f"❌ Normal pagination failed: {response.status_code}")
            return False
        
        # Count user rows in response
        user_count = response.text.count('testvoter')
        print(f"   Found {user_count} users (expected: 20 or less)")
        
        if user_count > 20:
            print(f"❌ SECURITY ISSUE: Expected max 20 users, got {user_count}")
            return False
        
        print("✅ Normal pagination working correctly")
        
        # Step 3: Test maximum allowed limit (should work)
        print("3️⃣ Testing maximum allowed limit (40 per page)...")
        response = session.get(f"{base_url}/admin/users?per_page=40")
        
        if response.status_code != 200:
            print(f"❌ Max limit test failed: {response.status_code}")
            return False
        
        user_count = response.text.count('testvoter')
        print(f"   Found {user_count} users (expected: 40 or less)")
        
        if user_count > 40:
            print(f"❌ SECURITY ISSUE: Expected max 40 users, got {user_count}")
            return False
        
        print("✅ Maximum limit working correctly")
        
        # Step 4: CRITICAL SECURITY TEST - Try to bypass limit
        print("4️⃣ 🚨 CRITICAL SECURITY TEST: Attempting to bypass 40-record limit...")
        
        # Test with 50 (just above limit)
        print("   Testing per_page=50...")
        response = session.get(f"{base_url}/admin/users?per_page=50")
        
        if response.status_code != 200:
            print(f"❌ Bypass test failed: {response.status_code}")
            return False
        
        user_count = response.text.count('testvoter')
        print(f"   Found {user_count} users (MUST be ≤40 for security)")
        
        if user_count > 40:
            print(f"🚨 CRITICAL SECURITY BREACH: Limit bypassed! Got {user_count} users")
            return False
        
        print("✅ Bypass attempt blocked successfully")
        
        # Step 5: EXTREME ATTACK TEST
        print("5️⃣ 🚨 EXTREME ATTACK TEST: Attempting massive limit...")
        
        print("   Testing per_page=99999 (DoS attack simulation)...")
        response = session.get(f"{base_url}/admin/users?per_page=99999")
        
        if response.status_code != 200:
            print(f"❌ Extreme attack test failed: {response.status_code}")
            return False
        
        user_count = response.text.count('testvoter')
        print(f"   Found {user_count} users (MUST be ≤40 for security)")
        
        if user_count > 40:
            print(f"🚨 CRITICAL SECURITY BREACH: DoS limit bypassed! Got {user_count} users")
            return False
        
        print("✅ DoS attack blocked successfully")
        
        # Step 6: Test invalid inputs
        print("6️⃣ Testing invalid inputs...")
        
        # Test with invalid string
        response = session.get(f"{base_url}/admin/users?per_page=abc")
        if response.status_code == 200:
            user_count = response.text.count('testvoter')
            print(f"   Invalid string test: {user_count} users (should be default)")
            if user_count > 40:
                print(f"❌ SECURITY ISSUE: Invalid input bypassed limit")
                return False
        
        # Test with negative number
        response = session.get(f"{base_url}/admin/users?per_page=-10")
        if response.status_code == 200:
            user_count = response.text.count('testvoter')
            print(f"   Negative number test: {user_count} users (should be default)")
            if user_count > 40:
                print(f"❌ SECURITY ISSUE: Negative input bypassed limit")
                return False
        
        print("✅ Invalid input handling working correctly")
        
        print("\n🎉 ALL SECURITY TESTS PASSED!")
        print("✅ Pagination limits are properly enforced")
        print("✅ DoS attacks are blocked")
        print("✅ Invalid inputs are handled safely")
        print("✅ Maximum 40 records per page enforced server-side")
        
        return True
        
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to Flask app. Make sure it's running on http://127.0.0.1:5000")
        return False
    except Exception as e:
        print(f"❌ Test error: {e}")
        return False


def test_direct_url_manipulation():
    """
    Test direct URL manipulation attempts.
    """
    print("\n🔗 Testing Direct URL Manipulation...")
    
    base_url = "http://127.0.0.1:5000"
    
    # Test without login (should redirect)
    try:
        response = requests.get(f"{base_url}/admin/users?per_page=99999", allow_redirects=False)
        print(f"   Unauthorized access: {response.status_code} (should be 302 redirect)")
        
        if response.status_code == 302:
            print("✅ Unauthorized access properly blocked")
        else:
            print("⚠️  Unexpected response for unauthorized access")
            
    except Exception as e:
        print(f"❌ URL manipulation test error: {e}")


if __name__ == "__main__":
    print("🧪 Pagination Security Integration Test")
    print("=" * 50)
    
    # Test the live application
    success = test_pagination_security_live()
    
    # Test URL manipulation
    test_direct_url_manipulation()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 SECURITY TEST RESULTS: PASS")
        print("The application is secure against pagination attacks!")
    else:
        print("🚨 SECURITY TEST RESULTS: FAIL") 
        print("CRITICAL: Security vulnerabilities detected!")
        
    print("\nTo run this test:")
    print("1. Start Flask app: python run_demo.py --no-input")
    print("2. Run this test: python test_pagination_security_live.py")