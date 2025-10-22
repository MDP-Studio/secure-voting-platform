#!/usr/bin/env python3
"""
Test Voter Creation Script

This script helps developers easily create test voters for the secure voting system.
It provides options to enable/disable test voter creation and recreate the database
with test data.

Usage:
    python create_test_voters.py --enable    # Enable test voter creation
    python create_test_voters.py --disable   # Disable test voter creation
    python create_test_voters.py --reset     # Reset database with test voters
    python create_test_voters.py --show      # Show current test voter settings
"""

import sys
import os
import argparse
from pathlib import Path

def update_env_file(enable_test_voters):
    """Update the .env file to enable or disable test voter creation."""
    env_file = Path('.env')
    if not env_file.exists():
        print("❌ .env file not found. Please copy .env.example to .env first.")
        return False
    
    # Read current content
    with open(env_file, 'r') as f:
        lines = f.readlines()
    
    # Update the CREATE_TEST_VOTERS line
    updated = False
    for i, line in enumerate(lines):
        if line.startswith('CREATE_TEST_VOTERS='):
            lines[i] = f'CREATE_TEST_VOTERS={"true" if enable_test_voters else "false"}\n'
            updated = True
            break
    
    # If the line doesn't exist, add it
    if not updated:
        lines.append(f'CREATE_TEST_VOTERS={"true" if enable_test_voters else "false"}\n')
    
    # Write back to file
    with open(env_file, 'w') as f:
        f.writelines(lines)
    
    status = "enabled" if enable_test_voters else "disabled"
    print(f"✅ Test voter creation {status} in .env file")
    return True

def show_current_status():
    """Show the current test voter creation status."""
    from dotenv import load_dotenv
    load_dotenv()
    
    status = os.environ.get('CREATE_TEST_VOTERS', 'false').lower() == 'true'
    status_text = "ENABLED" if status else "DISABLED"
    print(f"Current test voter creation status: {status_text}")
    
    # Try to import and show test voter count
    try:
        from app.generate_test_voters import get_test_voter_count
        count = get_test_voter_count()
        print(f"Available test voters: {count}")
    except ImportError:
        print("⚠️  Test voter generator not available")

def reset_database():
    """Reset the database and create test voters."""
    print("🔄 Resetting database with test voters...")
    
    # Enable test voters first
    if not update_env_file(True):
        return
    
    # Remove existing database
    db_file = Path('instance/app.db')
    if db_file.exists():
        db_file.unlink()
        print("🗑️  Removed existing database")
    
    # Run the database initialization
    try:
        from app import create_app
        from app.init_db import init_database
        
        app = create_app()
        init_database(app)
        print("✅ Database reset complete with test voters!")
        
    except Exception as e:
        print(f"❌ Failed to reset database: {e}")

def main():
    parser = argparse.ArgumentParser(description='Manage test voters for the voting system')
    parser.add_argument('--enable', action='store_true', help='Enable test voter creation')
    parser.add_argument('--disable', action='store_true', help='Disable test voter creation')
    parser.add_argument('--reset', action='store_true', help='Reset database with test voters')
    parser.add_argument('--show', action='store_true', help='Show current test voter settings')
    
    args = parser.parse_args()
    
    if args.enable:
        update_env_file(True)
        print("💡 Run 'python run_demo.py' to create the test voters")
    elif args.disable:
        update_env_file(False)
    elif args.reset:
        reset_database()
    elif args.show:
        show_current_status()
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python create_test_voters.py --enable   # Enable test voter creation")
        print("  python create_test_voters.py --reset    # Quick reset with test voters")
        print("  python create_test_voters.py --show     # Show current status")

if __name__ == "__main__":
    main()