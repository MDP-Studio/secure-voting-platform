#!/usr/bin/env python3
"""
Debug script for logout functionality

This script demonstrates how to debug authentication issues in the voting system.
It can be used as a reference for testing login/logout flows and session management.

Usage:
    python tests/debug_logout.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tests.integration.http_runner import HTTPTestRunner

def debug_logout():
    """Debug logout functionality step by step."""
    runner = HTTPTestRunner("http://localhost")

    print("=== Logout Functionality Debug ===")

    # Login
    print("\n1. Logging in...")
    login_success = runner.login('admin', 'admin123')
    print(f"   Login success: {login_success}")

    # Check authentication
    print("\n2. Checking authentication...")
    auth_before = runner.is_authenticated()
    print(f"   Authenticated before logout: {auth_before}")

    # Logout
    print("\n3. Logging out...")
    logout_response = runner.session.get(runner.base_url + '/logout', allow_redirects=False)
    print(f"   Logout response status: {logout_response.status_code}")
    print(f"   Logout response location: {logout_response.headers.get('Location', 'N/A')}")
    if logout_response.status_code == 302:
        print("   ✓ Logout returned proper redirect")
    else:
        print("   ✗ Logout did not return redirect")

    # Check authentication after logout
    print("\n4. Checking authentication after logout...")
    auth_after = runner.is_authenticated()
    print(f"   Authenticated after logout: {auth_after}")

    # Try accessing dashboard after logout
    dashboard_response = runner.session.get(runner.base_url + '/dashboard', allow_redirects=False)
    print(f"\n5. Dashboard access after logout: {dashboard_response.status_code}")
    if dashboard_response.status_code == 302:
        print(f"   ✓ Dashboard correctly redirects to: {dashboard_response.headers.get('Location', 'N/A')}")
    elif dashboard_response.status_code == 200:
        print("   ✗ Dashboard still accessible - logout failed")

    print("\n=== Debug Complete ===")

if __name__ == "__main__":
    debug_logout()