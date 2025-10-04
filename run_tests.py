#!/usr/bin/env python3
"""
Simple test runner for smoke tests.
Run with: python run_tests.py
"""

import subprocess
import sys
import os

def run_smoke_tests():
    """Run the smoke tests using pytest."""
    print("🚀 Running smoke tests...")

    # Install test dependencies if needed
    try:
        subprocess.run([
            sys.executable, '-m', 'pip', 'install', '-q', '-r', 'requirements-dev.txt'
        ], check=True)
    except subprocess.CalledProcessError:
        print("❌ Failed to install test dependencies")
        return False

    # Run the tests
    try:
        result = subprocess.run([
            sys.executable, '-m', 'pytest',
            'tests/test_smoke.py',
            '-v',  # verbose output
            '--tb=short',  # shorter traceback
            '--color=yes'  # colored output
        ], cwd=os.getcwd())

        if result.returncode == 0:
            print("✅ All smoke tests passed!")
            return True
        else:
            print(f"❌ Smoke tests failed with exit code {result.returncode}")
            return False

    except FileNotFoundError:
        print("❌ pytest not found. Please install pytest: pip install pytest")
        return False

if __name__ == '__main__':
    success = run_smoke_tests()
    sys.exit(0 if success else 1)