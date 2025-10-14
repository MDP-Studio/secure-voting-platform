#!/usr/bin/env python3
"""
Test script to verify rate limiting on the vote endpoint.
This script tests STRICT MODE first to verify rate limiting blocking works.
"""

import requests
import time
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from integration.conftest import HTTPTestRunner

def test_strict_mode_rate_limiting():
    """Test rate limiting in strict mode."""
    print('🧪 Testing STRICT MODE rate limiting on /vote endpoint')
    print('   Configuration: restrictive limits for production security')
    print('   Expected: Should trigger 503 Service Unavailable on burst exceed')
    print()

    runner = HTTPTestRunner("http://localhost:80")
    # No X-Test-Mode header = strict mode (restrictive limits)

    responses = []
    rate_limited_count = 0
    service_unavailable_count = 0

    # Make rapid requests to exceed the burst limit
    num_requests = 10  # Should exceed the burst limit

    print(f'Making {num_requests} rapid POST requests to /vote (strict mode)...')

    for i in range(num_requests):
        try:
            response = runner.post('/vote', data={'candidate_id': 1})
            responses.append(response.status_code)

            if response.status_code == 429:
                status_msg = f'Vote POST {i+1}: {response.status_code} ⚠️  RATE LIMITED!'
                rate_limited_count += 1
                print(f'\033[91m{status_msg}\033[0m')  # Red
            elif response.status_code == 503:
                status_msg = f'Vote POST {i+1}: {response.status_code} ⚠️  SERVICE UNAVAILABLE!'
                service_unavailable_count += 1
                print(f'\033[93m{status_msg}\033[0m')  # Yellow
            else:
                print(f'Vote POST {i+1}: {response.status_code}')

            # Very short delay to maintain rapid firing
            time.sleep(0.02)

        except Exception as e:
            responses.append('error')
            print(f'Vote POST {i+1}: ERROR - {e}')

    print(f'\n📊 STRICT MODE RESULTS:')
    print(f'   Total requests: {len(responses)}')
    print(f'   Rate limited (429): {rate_limited_count}')
    print(f'   Service unavailable (503): {service_unavailable_count}')
    print(f'   Successful responses: {responses.count(200) + responses.count(302) + responses.count(403)}')

    if rate_limited_count > 0 or service_unavailable_count > 0:
        print('\n✅ SUCCESS: Rate limiting is working in strict mode!')
        return True
    else:
        print('\n❌ FAILURE: No rate limiting detected in strict mode')
        print('   The nginx limit_req module may not be active or limits are too high.')
        return False

def test_test_mode_rate_limiting():
    """Test rate limiting in test mode (relaxed limits)."""
    print('\n🧪 Testing TEST MODE rate limiting on /vote endpoint')
    print('   Configuration: relaxed limits for development/integration testing')
    print('   Expected: Should allow more requests before limiting')
    print()

    runner = HTTPTestRunner("http://localhost:80")
    # Add test mode header for relaxed limits
    runner.session.headers.update({'X-Test-Mode': '1'})

    responses = []
    rate_limited_count = 0
    service_unavailable_count = 0

    # Make requests to potentially trigger rate limiting
    num_requests = 10  # Should exceed burst limits but within reasonable test limits

    print(f'Making {num_requests} rapid POST requests to /vote (test mode)...')

    for i in range(num_requests):
        try:
            response = runner.post('/vote', data={'candidate_id': 1})
            responses.append(response.status_code)

            if response.status_code == 429:
                status_msg = f'Vote POST {i+1}: {response.status_code} ⚠️  RATE LIMITED!'
                rate_limited_count += 1
                print(f'\033[91m{status_msg}\033[0m')
            elif response.status_code == 503:
                status_msg = f'Vote POST {i+1}: {response.status_code} ⚠️  SERVICE UNAVAILABLE!'
                service_unavailable_count += 1
                print(f'\033[93m{status_msg}\033[0m')
            else:
                print(f'Vote POST {i+1}: {response.status_code}')

            time.sleep(0.02)

        except Exception as e:
            responses.append('error')
            print(f'Vote POST {i+1}: ERROR - {e}')

    print(f'\n📊 TEST MODE RESULTS:')
    print(f'   Total requests: {len(responses)}')
    print(f'   Rate limited (429): {rate_limited_count}')
    print(f'   Service unavailable (503): {service_unavailable_count}')
    print(f'   Successful responses: {responses.count(200) + responses.count(302) + responses.count(403)}')

    if rate_limited_count > 0 or service_unavailable_count > 0:
        print('\n✅ SUCCESS: Rate limiting is working in test mode!')
        return True
    else:
        print('\n⚠️  No rate limiting triggered in test mode (may be expected with relaxed limits)')
        return None  # Not a failure, just not triggered

if __name__ == '__main__':
    print('Rate Limiting Test for Vote Endpoint')
    print('=====================================')
    print('Testing STRICT MODE first to verify blocking works...')
    print()

    # Test strict mode first
    strict_success = test_strict_mode_rate_limiting()

    # Then test relaxed mode
    test_success = test_test_mode_rate_limiting()

    print(f'\n{"="*50}')
    print('FINAL SUMMARY:')
    if strict_success:
        print('🎉 Rate limiting is working correctly!')
        print('   ✅ Strict mode blocks excessive requests')
        if test_success:
            print('   ✅ Test mode also working (different limits)')
        elif test_success is None:
            print('   ⚠️  Test mode limits not triggered (may be expected)')
    else:
        print('❌ Rate limiting investigation needed')
        print('   - Check if nginx limit_req module is compiled in')
        print('   - Verify configuration is loaded correctly')
        print('   - Check nginx error logs for issues')