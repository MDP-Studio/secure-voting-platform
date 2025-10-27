#!/usr/bin/env python3
"""
Quick test of login and dashboard access for debugging.
Run this from the repo root: python tests/debug_login.py
"""

import sys
sys.path.insert(0, '/c/Users/colin/sec-soft-sys-a3')

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from tests.integration.conftest import HTTPTestRunner

def main():
    # Test with local HTTP runner (adjust base_url as needed)
    runner = HTTPTestRunner("http://localhost")  # Docker setup with WAF
    
    print("\n" + "="*80)
    print("Testing admin login...")
    print("="*80)
    
    success = runner.login('admin', 'Admin@123456!')
    print(f"\nLogin returned: {success}")
    print(f"Session cookies: {dict(runner.session.cookies)}")
    
    print("\n" + "="*80)
    print("Testing dashboard access after login...")
    print("="*80)
    
    response = runner.get('/dashboard')
    print(f"Dashboard response status: {response.status_code}")
    print(f"'welcome' in response: {'welcome' in response.text.lower()}")
    print(f"'login' in response: {'login' in response.text.lower()}")
    print(f"Response first 500 chars:\n{response.text[:500]}")

if __name__ == '__main__':
    main()
