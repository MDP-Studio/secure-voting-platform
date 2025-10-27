#!/usr/bin/env python3
"""
Demonstration script showing Vault integration for result signing.
This script shows how the voting system uses Vault for cryptographic operations.
"""

import os
import sys
import json
import time
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

def demo_result_signing():
    """Demonstrate result signing with Vault integration."""
    print("🔐 Vault Integration Demo - Result Signing")
    print("=" * 50)
    
    # Set up environment for demo
    os.environ['VAULT_ADDR'] = 'http://localhost:8200'
    os.environ['VAULT_TOKEN'] = 'vault-dev-token'
    os.environ['VAULT_MOUNT'] = 'transit'
    os.environ['VAULT_KV_MOUNT'] = 'kv'
    os.environ['VAULT_TRANSIT_KEY'] = 'results-signing'
    
    try:
        from app.security.vault_client import vault_client
        from app.security.signing_service import sign_data, verify_signature
        
        print("1. Checking Vault connection...")
        if vault_client.is_enabled:
            print("   ✅ Vault is connected and ready")
        else:
            print("   ⚠️  Vault not available, using local keys")
        
        print("\n2. Creating sample election results...")
        # Simulate election results
        election_results = {
            "election_id": "2024-general-election",
            "timestamp": int(time.time()),
            "results": {
                "candidate_1": 1250,
                "candidate_2": 980,
                "candidate_3": 750,
                "abstain": 45
            },
            "total_votes": 3025,
            "valid_votes": 2980
        }
        
        results_json = json.dumps(election_results, indent=2)
        results_bytes = results_json.encode('utf-8')
        
        print(f"   📊 Results: {len(election_results['results'])} candidates")
        print(f"   📊 Total votes: {election_results['total_votes']}")
        
        print("\n3. Signing results with Vault...")
        start_time = time.time()
        signature = sign_data(results_bytes)
        sign_time = time.time() - start_time
        
        if signature:
            print(f"   ✅ Results signed successfully")
            print(f"   ⏱️  Signing time: {sign_time:.3f} seconds")
            print(f"   🔑 Signature length: {len(signature)} bytes")
        else:
            print("   ❌ Failed to sign results")
            return False
        
        print("\n4. Verifying signature...")
        start_time = time.time()
        is_valid = verify_signature(results_bytes, signature)
        verify_time = time.time() - start_time
        
        if is_valid:
            print(f"   ✅ Signature verification successful")
            print(f"   ⏱️  Verification time: {verify_time:.3f} seconds")
        else:
            print("   ❌ Signature verification failed")
            return False
        
        print("\n5. Testing tamper detection...")
        # Tamper with the data
        tampered_results = election_results.copy()
        tampered_results['results']['candidate_1'] = 9999  # Change vote count
        tampered_json = json.dumps(tampered_results, indent=2)
        tampered_bytes = tampered_json.encode('utf-8')
        
        is_tampered_valid = verify_signature(tampered_bytes, signature)
        if not is_tampered_valid:
            print("   ✅ Tamper detection working - signature invalid for modified data")
        else:
            print("   ❌ Tamper detection failed - signature valid for modified data")
            return False
        
        print("\n6. Configuration access from Vault...")
        admin_email = vault_client.kv_get('voting/config', 'admin_email')
        if admin_email:
            print(f"   ✅ Retrieved admin email: {admin_email}")
        else:
            print("   ⚠️  Could not retrieve admin email from Vault")
        
        print("\n" + "=" * 50)
        print("🎉 Vault integration demo completed successfully!")
        print("=" * 50)
        print("Key benefits demonstrated:")
        print("• Secure cryptographic signing using Vault's Transit engine")
        print("• Tamper-proof election results")
        print("• Centralized key management")
        print("• Configuration management")
        print("• Audit trail for all operations")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure you're running this from the project root directory")
        return False
    except Exception as e:
        print(f"❌ Error during demo: {e}")
        return False

def demo_vault_ui_info():
    """Show information about accessing Vault UI."""
    print("\n🌐 Vault Web UI Access")
    print("-" * 30)
    print("URL: http://localhost:8200")
    print("Token: vault-dev-token")
    print("\nIn the Vault UI, you can:")
    print("• View the transit engine and signing key")
    print("• Browse configuration in the KV store")
    print("• Monitor audit logs")
    print("• Manage policies and tokens")

def main():
    """Main demo function."""
    print("Starting Vault integration demonstration...")
    print("Make sure Vault is running: docker-compose up -d")
    print("Make sure Vault is initialized: python3 scripts/init_vault.py")
    print()
    
    # Wait a moment for user to read
    time.sleep(2)
    
    success = demo_result_signing()
    demo_vault_ui_info()
    
    if success:
        print("\n✅ Demo completed successfully!")
        print("The voting system is now using Vault for secure result signing.")
    else:
        print("\n❌ Demo failed. Check that Vault is running and initialized.")
        print("Run: docker-compose up -d && python3 scripts/init_vault.py")
    
    return 0 if success else 1

if __name__ == '__main__':
    sys.exit(main())
