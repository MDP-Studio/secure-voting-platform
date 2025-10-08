#!/usr/bin/env python3
"""
🛡️ WAF Functionality Demonstration Tool

QUICK LINKS:
• Direct App:     [http://localhost:8000](http://localhost:8000)
• WAF Protected:  [http://localhost](http://localhost)
• README:         [README.md](README.md)
• Test Docs:      [tests/README.md](tests/README.md)

This script demonstrates the security benefits of the Web Application Firewall (WAF)
by comparing direct access to the Flask application vs access through the WAF-protected endpoint.

OVERVIEW:
---------
This tool tests two access methods:
• Direct Flask App: [http://localhost:8000](http://localhost:8000) (no WAF protection)
• WAF Protected:    [http://localhost](http://localhost)  (with nginx + ModSecurity)

The demonstration shows how the WAF blocks malicious payloads while allowing legitimate traffic.

USAGE:
------
python test_waf_demo.py

WHAT IT TESTS:
• Normal endpoints (/, /login, /register, /health/healthz)
• Malicious payloads (XSS scripts, SQL injection, JavaScript URLs)
• Security comparison between direct vs WAF-protected access

EXPECTED RESULTS:
• Normal traffic: ✅ Works on both direct and WAF
• Malicious payloads: ⚠️ Allowed on direct, 🛡️ Blocked by WAF
"""

import requests
import json
import time

# Disable SSL warnings for self-signed certs (if any)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ANSI color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    GRAY = '\033[90m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

class WAFTester:
    def __init__(self):
        # Direct Flask app access (no WAF protection)
        # Link: http://localhost:8000
        self.direct_url = "http://localhost:8000"  # Direct Flask app (no WAF)

        # WAF-protected access through nginx + ModSecurity
        # Link: http://localhost:80
        self.waf_url = "http://localhost:80"       # Through WAF

    def test_endpoint(self, url: str, endpoint: str, description: str) -> dict:
        """Test an endpoint and return response details."""
        try:
            response = requests.get(f"{url}{endpoint}", timeout=5)
            return {
                'status_code': response.status_code,
                'content_length': len(response.text),
                'blocked': response.status_code == 403,
                'success': response.status_code == 200,
                'content_preview': response.text[:200] + "..." if len(response.text) > 200 else response.text
            }
        except requests.exceptions.RequestException as e:
            return {
                'status_code': None,
                'error': str(e),
                'blocked': False,
                'success': False
            }

    def test_malicious_payload(self, url: str, payload: str, description: str) -> dict:
        """Test a malicious payload in login form."""
        try:
            data = {
                'username': payload,
                'password': 'test123'
            }
            response = requests.post(f"{url}/login", data=data, timeout=5, allow_redirects=False)
            return {
                'status_code': response.status_code,
                'content_length': len(response.text),
                'blocked': response.status_code == 403,
                'success': response.status_code in [200, 302],
                'content_preview': response.text[:200] + "..." if len(response.text) > 200 else response.text
            }
        except requests.exceptions.RequestException as e:
            return {
                'status_code': None,
                'error': str(e),
                'blocked': False,
                'success': False
            }

    def print_header(self):
        """Print the demonstration header."""
        print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 80}{Colors.END}")
        print(f"{Colors.BOLD}{Colors.CYAN}🛡️  WAF FUNCTIONALITY DEMONSTRATION{Colors.END}")
        print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 80}{Colors.END}")
        print()

    def print_section_header(self, title: str, emoji: str = ""):
        """Print a section header."""
        print(f"{Colors.BOLD}{Colors.YELLOW}{title}{Colors.END}")
        print(f"{Colors.YELLOW}{'-' * (len(title) + len(emoji))}{Colors.END}")

    def print_endpoint_result(self, label: str, result: dict, is_direct: bool):
        """Print endpoint test result."""
        status_color = Colors.GREEN if result['success'] else Colors.RED
        status_icon = "✅" if result['success'] else "❌"
        port_info = f"{Colors.BLUE}Direct (port 8000){Colors.END}" if is_direct else f"{Colors.MAGENTA}Through WAF (port 80){Colors.END}"

        print(f"  {port_info}: Status {Colors.BOLD}{result['status_code']}{Colors.END} - {status_color}{status_icon}{Colors.END}")

        if result.get('error'):
            print(f"    {Colors.RED}❌ Error: {result['error']}{Colors.END}")

    def print_payload_result(self, payload: str, description: str, direct_result: dict, waf_result: dict):
        """Print malicious payload test result."""
        print(f"{Colors.BOLD}{Colors.CYAN}🎯 {description}:{Colors.END}")
        print(f"  {Colors.GRAY}Payload: {payload}{Colors.END}")

        # Direct access result
        direct_status = "ALLOWED" if not direct_result['blocked'] else "BLOCKED"
        direct_color = Colors.RED if direct_result['blocked'] else Colors.YELLOW
        direct_icon = "🚫" if direct_result['blocked'] else "⚠️"

        # WAF result
        waf_status = "BLOCKED" if waf_result['blocked'] else "ALLOWED"
        waf_color = Colors.GREEN if waf_result['blocked'] else Colors.RED
        waf_icon = "🛡️" if waf_result['blocked'] else "❌"

        print(f"  {Colors.BLUE}Direct (port 8000):   {Colors.END} Status {direct_result['status_code']} - {direct_color}{direct_icon}  {direct_status}  {Colors.END}")
        print(f"  {Colors.MAGENTA}Through WAF (port 80):{Colors.END} Status {waf_result['status_code']} - {waf_color}{waf_icon}  {waf_status}  {Colors.END}")

        if direct_result.get('error'):
            print(f"    {Colors.RED}❌ Direct error: {direct_result['error']}{Colors.END}")
        if waf_result.get('error'):
            print(f"    {Colors.RED}❌ WAF error: {waf_result['error']}{Colors.END}")

    def run_comparison_test(self):
        """Run comprehensive comparison between direct access and WAF-protected access."""

        self.print_header()

        # Test normal endpoints
        self.print_section_header("1. TESTING NORMAL ENDPOINTS 🌐", "🌐")

        endpoints = [
            ('/', 'Home page'),
            ('/login', 'Login page (redirects to home)'),
            ('/register', 'Registration page'),
            ('/health/healthz', 'Health check')
        ]

        for endpoint, description in endpoints:
            print(f"\n{Colors.BOLD}{description} ({endpoint}):{Colors.END}")

            direct_result = self.test_endpoint(self.direct_url, endpoint, description)
            waf_result = self.test_endpoint(self.waf_url, endpoint, description)

            self.print_endpoint_result(description, direct_result, True)
            self.print_endpoint_result(description, waf_result, False)

        # Test malicious payloads
        print(f"\n\n{Colors.BOLD}{Colors.RED}2. TESTING MALICIOUS PAYLOADS (XSS/SQL Injection) ⚠️{Colors.END}")
        print(f"{Colors.RED}{'-' * 60}{Colors.END}")

        payloads = [
            ("<script>alert('xss')</script>", "XSS Script Tag"),
            ("<img src=x onerror=alert(1)>", "XSS Image with onerror"),
            ("' OR '1'='1", "SQL Injection"),
            ("<svg onload=alert(1)>", "XSS SVG onload"),
            ("javascript:alert('xss')", "JavaScript URL")
        ]

        blocked_direct = 0
        blocked_waf = 0

        for payload, description in payloads:
            print()
            direct_result = self.test_malicious_payload(self.direct_url, payload, description)
            waf_result = self.test_malicious_payload(self.waf_url, payload, description)

            if direct_result['blocked']:
                blocked_direct += 1
            if waf_result['blocked']:
                blocked_waf += 1

            self.print_payload_result(payload, description, direct_result, waf_result)

        # Summary
        print(f"\n\n{Colors.BOLD}{Colors.BLUE}3. SUMMARY 📊{Colors.END}")
        print(f"{Colors.BLUE}{'-' * 12}{Colors.END}")
        print(f"📋 Normal endpoints tested: {Colors.BOLD}{len(endpoints)}{Colors.END}")
        print(f"🎯 Malicious payloads tested: {Colors.BOLD}{len(payloads)}{Colors.END}")
        print(f"🚫 Payloads blocked by direct access: {Colors.BOLD}{blocked_direct}/{len(payloads)}{Colors.END}")
        print(f"🛡️  Payloads blocked by WAF: {Colors.BOLD}{blocked_waf}/{len(payloads)}{Colors.END}")

        if blocked_waf > blocked_direct:
            print(f"\n{Colors.GREEN}✅ SUCCESS: WAF provides additional security by blocking malicious requests!{Colors.END}")
            print(f"   {Colors.GREEN}🛡️  WAF blocked {blocked_waf - blocked_direct} more malicious payloads than direct access.{Colors.END}")
        else:
            print(f"\n{Colors.RED}⚠️  WARNING: WAF may not be functioning as expected.{Colors.END}")

        print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 80}{Colors.END}")

if __name__ == "__main__":
    tester = WAFTester()
    tester.run_comparison_test()