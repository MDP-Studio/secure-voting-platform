#!/usr/bin/env python
"""Debug login flow."""

import requests
import json

# Create a session to maintain cookies
session = requests.Session()

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
r = session.post('http://localhost/login', data=login_data, allow_redirects=False)
print(f"Status: {r.status_code}")
print(f"Location header: {r.headers.get('Location', 'N/A')}")
if r.status_code == 200:
    print(f"Response contains 'login': {'login' in r.text.lower()}")
    print(f"Response preview: {r.text[:300]}")
