#!/usr/bin/env python3
"""
Unit tests for the get_safe_page_limit function.
Tests the core pagination security logic without Flask app context.
"""

import sys
import os

# Add the app directory to the path so we can import the function
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

def test_get_safe_page_limit_basic():
    """
    Test the get_safe_page_limit function with a mock app context.
    """
    print("🔧 Testing get_safe_page_limit function...")
    
    # Create a simple mock for current_app.logger
    class MockLogger:
        def warning(self, msg):
            print(f"   [LOG WARNING] {msg}")
        def error(self, msg):
            print(f"   [LOG ERROR] {msg}")
    
    class MockCurrentApp:
        logger = MockLogger()
    
    # Mock the current_app
    import unittest.mock
    with unittest.mock.patch('app.routes.admin_users.current_app', MockCurrentApp()), \
         unittest.mock.patch('app.routes.admin_users.flask_request') as mock_request:
        
        # Mock the request object for IP logging
        mock_request.environ.get.return_value = '127.0.0.1'
        mock_request.remote_addr = '127.0.0.1'
        
        from app.routes.admin_users import get_safe_page_limit
        
        # Test normal valid values
        print("✅ Testing normal valid values...")
        assert get_safe_page_limit('10') == 10
        assert get_safe_page_limit('20') == 20
        assert get_safe_page_limit('40') == 40
        print("   Normal values: PASS")
        
        # Test edge cases
        print("✅ Testing edge cases...")
        assert get_safe_page_limit('1') == 1  # Minimum valid
        assert get_safe_page_limit('0') == 10  # Invalid zero
        assert get_safe_page_limit('-5') == 10  # Invalid negative
        print("   Edge cases: PASS")
        
        # CRITICAL SECURITY TESTS
        print("🚨 CRITICAL SECURITY TESTS...")
        assert get_safe_page_limit('41') == 40  # Just above limit
        assert get_safe_page_limit('100') == 40  # Well above limit
        assert get_safe_page_limit('999999') == 40  # Attack attempt
        print("   Security boundary: PASS")
        
        # Test invalid inputs
        print("✅ Testing invalid inputs...")
        assert get_safe_page_limit('abc') == 20  # Invalid string
        assert get_safe_page_limit('') == 20  # Empty string
        assert get_safe_page_limit(None) == 20  # None value
        assert get_safe_page_limit('10.5') == 20  # Float string
        print("   Invalid inputs: PASS")
        
        # Test with custom max_limit (should still respect absolute max)
        print("✅ Testing custom max_limit...")
        assert get_safe_page_limit('50', max_limit=30) == 30
        assert get_safe_page_limit('50', max_limit=50) == 40  # Absolute max wins
        print("   Custom limits: PASS")
        
    print("🎉 All unit tests PASSED!")
    return True


if __name__ == "__main__":
    print("🧪 Unit Tests for Pagination Security")
    print("=" * 40)
    
    try:
        success = test_get_safe_page_limit_basic()
        print("\n" + "=" * 40)
        if success:
            print("🎉 UNIT TEST RESULTS: PASS")
        else:
            print("🚨 UNIT TEST RESULTS: FAIL")
    except Exception as e:
        print(f"❌ Unit test error: {e}")
        print("🚨 UNIT TEST RESULTS: FAIL")