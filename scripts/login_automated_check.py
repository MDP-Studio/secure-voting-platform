#!/usr/bin/env python3
"""Automated tests for login human-check protections.

Usage: python scripts/test_login_automated.py --base http://127.0.0.1:5000 --metrics
"""
import argparse
import sys
import requests

def show(name, resp):
    print('---', name, '---')
    print('Status:', resp.status_code)
    text = resp.text
    snippet = text[:1000] + ('...' if len(text) > 1000 else '')
    print(snippet)
    # Try to detect common rejection flash messages to explain why the request failed
    reasons = detect_rejection_reason(text)
    if reasons:
        print('\nDetected reason(s):')
        for r in reasons:
            print('- ' + r)
    print()


def detect_rejection_reason(html_text: str):
    """Return list of likely rejection reasons found in HTML text (simple heuristics)."""
    candidates = []
    low = html_text.lower()
    # common flash messages we expect from auth.py
    checks = [
        ("human verification required", "Missing or invalid login nonce / required browser JS"),
        ("human verification expired", "Nonce expired (reload login page)"),
        ("human verification failed", "Invalid human verification (Turnstile or nonce failed)"),
        ("please use a web browser to log in", "Blocked because a command-line client was detected (UA)") ,
        ("bot-like activity detected", "Honeypot (gotcha) was filled)") ,
        ("bot-like activity", "Honeypot (gotcha) was filled"),
        ("turnstile", "Turnstile related failure"),
        ("please complete the turnstile check", "Missing Turnstile token"),
        ("invalid password", "Invalid password (not human-check related)")
    ]
    for fragment, reason in checks:
        if fragment in low:
            candidates.append(reason)
    return list(dict.fromkeys(candidates))

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', '-b', default='http://127.0.0.1:5000')
    p.add_argument('--metrics', action='store_true')
    args = p.parse_args()
    b = args.base.rstrip('/')

    # Test 1: no nonce, CLI UA
    try:
        r1 = requests.post(b + '/login', data={'username':'testuser','password':'x'}, headers={'User-Agent':'curl/7.85.0'}, timeout=5)
        show('No-nonce with curl UA', r1)
    except Exception as e:
        print('No-nonce test error', e)

    # Test 2: gotcha field
    try:
        r2 = requests.post(b + '/login', data={'username':'testuser','password':'x','gotcha':'botfilled'}, timeout=5)
        show('Gotcha-filled', r2)
    except Exception as e:
        print('Gotcha test error', e)

    # Test 3: fetch nonce then post with browser headers
    try:
        s = requests.Session()
        n = s.get(b + '/login-nonce', timeout=5)
        j = n.json()
        nonce = j.get('nonce')
        print('Fetched nonce:', nonce)
        r3 = s.post(b + '/login', data={'username':'testuser','password':'x','login_nonce':nonce}, headers={'User-Agent':'Mozilla/5.0','Origin':b}, timeout=5)
        show('Nonce + browser-like headers', r3)
    except Exception as e:
        print('Nonce test error', e)

    if args.metrics:
        try:
            m = requests.get(b + '/metrics', timeout=5)
            print('--- /metrics ---')
            print(m.text)
        except Exception as e:
            print('Metrics fetch error', e)

if __name__ == '__main__':
    main()
