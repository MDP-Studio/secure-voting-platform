#!/usr/bin/env python3
"""
Test script to verify Vault integration with the voting system.
"""

import os
import sys
import time
import requests
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

def test_vault_connectivity():
    """Test basic Vault connectivity."""
    print("Testing Vault connectivity...")
    
    try:
        response = requests.get("http://localhost:8200/v1/sys/health", timeout=5)
        if response.status_code == 200:
            print("✓ Vault is accessible")
            return True
        else:
            print(f"✗ Vault returned status {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"✗ Cannot connect to Vault: {e}")
        return False

def test_vault_authentication():
    """Test Vault authentication."""
    print("Testing Vault authentication...")
    
    try:
        import hvac
        client = hvac.Client(url="http://localhost:8200", token="vault-dev-token")
        
        if client.is_authenticated():
            print("✓ Vault authentication successful")
            return True
        else:
            print("✗ Vault authentication failed")
            return False
    except ImportError:
        print("✗ hvac library not installed")
        return False
    except Exception as e:
        print(f"✗ Authentication error: {e}")
        return False

def test_transit_engine():
    """Test transit engine functionality."""
    print("Testing transit engine...")
    
    try:
        import hvac
        client = hvac.Client(url="http://localhost:8200", token="vault-dev-token")
        
        # Test signing
        test_data = b"test data for signing"
        response = client.secrets.transit.sign_data(
            name='results-signing',
            hash_algorithm='sha2-256',
            input=test_data.hex()
        )
        
        if 'data' in response and 'signature' in response['data']:
            print("✓ Transit signing works")
            
            # Test verification
            signature = response['data']['signature']
            verify_response = client.secrets.transit.verify_signed_data(
                name='results-signing',
                hash_algorithm='sha2-256',
                input=test_data.hex(),
                signature=signature
            )
            
            if verify_response['data']['valid']:
                print("✓ Transit verification works")
                return True
            else:
                print("✗ Transit verification failed")
                return False
        else:
            print("✗ Transit signing failed")
            return False
            
    except Exception as e:
        print(f"✗ Transit engine error: {e}")
        return False

def test_kv_store():
    """Test KV store functionality."""
    print("Testing KV store...")
    
    try:
        import hvac
        client = hvac.Client(url="http://localhost:8200", token="vault-dev-token")
        
        # Test reading configuration
        response = client.secrets.kv.v2.read_secret_version(
            path='voting/config',
            mount_point='kv'
        )
        
        if 'data' in response and 'data' in response['data']:
            config = response['data']['data']
            if 'admin_email' in config:
                print("✓ KV store reading works")
                return True
            else:
                print("✗ KV store data incomplete")
                return False
        else:
            print("✗ KV store read failed")
            return False
            
    except Exception as e:
        print(f"✗ KV store error: {e}")
        return False

def test_voting_integration():
    """Test the voting system's Vault integration."""
    print("Testing voting system integration...")
    
    try:
        # Set up environment for testing
        os.environ['VAULT_ADDR'] = 'http://localhost:8200'
        os.environ['VAULT_TOKEN'] = 'vault-dev-token'
        os.environ['VAULT_MOUNT'] = 'transit'
        os.environ['VAULT_KV_MOUNT'] = 'kv'
        os.environ['VAULT_TRANSIT_KEY'] = 'results-signing'
        
        from app.security.vault_client import vault_client
        from app.security.signing_service import sign_data, verify_signature
        
        # Test if Vault client is enabled
        if not vault_client.is_enabled:
            print("✗ Vault client not enabled")
            return False
        
        print("✓ Vault client is enabled")
        
        # Test signing through the voting system
        test_data = b"election results test data"
        signature = sign_data(test_data)
        
        if signature:
            print("✓ Voting system signing works")
            
            # Test verification
            is_valid = verify_signature(test_data, signature)
            if is_valid:
                print("✓ Voting system verification works")
                return True
            else:
                print("✗ Voting system verification failed")
                return False
        else:
            print("✗ Voting system signing failed")
            return False
            
    except Exception as e:
        print(f"✗ Voting system integration error: {e}")
        return False

def main():
    """Run all Vault integration tests."""
    print("Vault Integration Test Suite")
    print("=" * 40)
    
    tests = [
        test_vault_connectivity,
        test_vault_authentication,
        test_transit_engine,
        test_kv_store,
        test_voting_integration
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
            print()  # Add spacing between tests
        except Exception as e:
            print(f"✗ Test failed with exception: {e}")
            print()
    
    print("=" * 40)
    print(f"Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Vault integration is working correctly.")
        return 0
    else:
        print("❌ Some tests failed. Check the output above for details.")
        return 1

if __name__ == '__main__':
    sys.exit(main())
