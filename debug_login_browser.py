#!/usr/bin/env python
"""Debug login flow with browser User-Agent."""

import requests
import json

# Create a session to maintain cookies
session = requests.Session()

# Spoof a browser User-Agent
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})

# Step 1: GET the login page
print("=== Step 1: GET /login ===")
r = session.get('http://localhost/login')
print(f"Status: {r.status_code}")

# Step 2: GET the nonce
print("\n=== Step 2: GET /login-nonce ===")
r = session.get('http://localhost/login-nonce')
print(f"Status: {r.status_code}")
nonce_data = r.json()
nonce = nonce_data.get('nonce')
print(f"Nonce: {nonce}")

# Step 3: POST login with credentials and nonce
print("\n=== Step 3: POST /login ===")
login_data = {
    'username': 'admin',
    'password': 'Admin@123456!',
    'login_nonce': nonce
}
print(f"Sending: {login_data}")

# Add Referer header to satisfy Origin/Referer check
headers = {
    'Referer': 'http://localhost/login'
}

r = session.post('http://localhost/login', data=login_data, headers=headers, allow_redirects=False)
print(f"Status: {r.status_code}")
print(f"Location header: {r.headers.get('Location', 'N/A')}")
if r.status_code == 200:
    print(f"Response contains 'login': {'login' in r.text.lower()}")
    if 'error' in r.text.lower() or 'flash' in r.text.lower():
        # Try to extract the error message
        import re
        msg_match = re.search(r'<div[^>]*class="[^"]*alert[^"]*"[^>]*>([^<]+)<', r.text)
        if msg_match:
            print(f"Error message: {msg_match.group(1)}")
