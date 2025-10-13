# Testing Guide

This guide covers the comprehensive testing suite for the Secure Voting System, including integration, regression, penetration, and security testing.

## Test Structure

```
tests/
├── conftest.py                 # Pytest configuration and fixtures
├── test_smoke.py              # Basic smoke tests (13 tests)
├── integration/
│   ├── http_runner.py         # HTTP testing framework
│   ├── test_integration.py    # General integration tests (11 tests)
│   └── test_waf_security.py   # WAF security tests (16 tests)
└── debug_logout.py           # Debug example for logout testing
```

## Test Categories

### 1. Smoke Tests (`test_smoke.py`)
Basic functionality tests to ensure the application starts and core features work.

**Run smoke tests:**
```bash
python -m pytest tests/test_smoke.py -v
```

### 2. Integration Tests (`test_integration.py`)
Comprehensive tests covering:
- Health checks and static assets
- Authentication flows (login/logout)
- API access controls and authorization
- Dashboard and results page access

**Run integration tests:**
```bash
# With Docker containers
docker-compose up -d
# docker-compose up -d --build # (rebuild containers if needed)
python -m pytest tests/integration/test_integration.py -v --base-url=http://localhost

# With local Flask app
python -m pytest tests/integration/test_integration.py -v --base-url=http://localhost:5000
```

### 3. WAF Security Tests (`test_waf_security.py`)
Advanced security testing with real OWASP ModSecurity CRS:
- SQL injection attack vectors (7 test cases)
- XSS vulnerability checks (6 test cases)
- Rate limiting validation
- Security headers verification
- Malicious pattern detection

**Run WAF security tests:**
```bash
# Requires Docker setup with WAF
docker-compose up -d
# docker-compose up -d --build # (rebuild containers if needed)
python -m pytest tests/integration/test_waf_security.py -v --base-url=http://localhost
```

## Test Configuration

### Pytest Fixtures

- `http_runner`: Base HTTP test runner instance
- `clean_session`: Fresh session for each test (clears cookies)

### Command Line Options

- `--base-url`: Specify the base URL for testing (default: http://localhost:5000)
- `-v`: Verbose output
- `--tb=short`: Shorter traceback format

### Rate Limiting Considerations

The WAF implements rate limiting that may affect tests:
- General endpoints: 200 requests/minute
- Voting endpoint: 10 requests/minute
- Dev endpoints: 100 requests/minute

Tests include automatic delays to avoid rate limiting.

## Test Results Summary

### Integration Tests (11 tests)
- ✅ Health checks and static assets
- ✅ Authentication flows (login/logout)
- ✅ API access controls
- ✅ Admin-only functionality

### WAF Security Tests (16 tests)
- ✅ SQL injection blocking
- ✅ XSS prevention
- ✅ Rate limiting
- ✅ Security headers
- ✅ Malicious pattern detection

## Running All Tests

```bash
# Run all tests
python run_tests.py

# Or run specific categories
python -m pytest tests/ -v --base-url=http://localhost

# Run with coverage
python -m pytest tests/ --cov=app --cov-report=html
```

## Test Environment Setup

### Docker Environment (Recommended)
```bash
# Start all services
docker-compose up -d

# Run tests
python -m pytest tests/integration/ -v --base-url=http://localhost

# View logs
docker-compose logs -f
```

### Local Development Environment
```bash
# Install dependencies
pip install -r requirements-dev.txt

# or (recommended)
python -m pip install -r requirements-dev.txt

# Start Flask app
python run_demo.py

# Run tests in another terminal
python -m pytest tests/integration/test_integration.py -v --base-url=http://localhost:5000
```

## Debugging Tests

### Debug Examples
- `tests/debug_logout.py`: Example of debugging logout functionality
- Check Docker logs: `docker-compose logs waf` and `docker-compose logs web`

### Common Issues
1. **Rate limiting**: Tests may fail with 503 errors - increase rate limits in `nginx/conf.d/waf.conf`
2. **Container connectivity**: Ensure all containers are running with `docker-compose ps`
3. **Session issues**: Clear browser cookies or use incognito mode

### Test Logs
```bash
# View test output with logs
python -m pytest tests/ -v -s

# Save test results
python -m pytest tests/ --junitxml=test-results.xml
```

## Security Test Validation

The WAF security tests validate real OWASP ModSecurity CRS functionality:

- **SQL Injection**: Tests various injection patterns that should be blocked
- **XSS**: Tests script injection attempts that should be prevented
- **Rate Limiting**: Verifies proper throttling of excessive requests
- **Headers**: Confirms security headers are present and correct
- **Patterns**: Tests detection of malicious request patterns

All security tests should pass when the WAF is properly configured.

## Developer Dashboard

The development dashboard (`http://localhost/dev/dashboard`) provides comprehensive system monitoring and debugging capabilities:

### Features

- **System Information**: Platform, Python version, CPU/memory usage, disk space
- **Application Information**: Flask version, debug mode, database configuration
- **Client Connection Info**: IP addresses, user agents, headers
- **Database Contents**: Users, candidates, votes with statistics
- **Real-time Logs**: Web server logs and WAF logs loaded via AJAX

### Log Loading

Logs are now loaded asynchronously via AJAX from the `/dev/logs` API endpoint:

- **Web Server Logs**: Flask application logs from `instance/app.log`
- **WAF Logs**: Nginx access/error logs from Docker containers using `docker-compose logs waf`
- **Auto-refresh**: Logs refresh every 30 seconds automatically
- **Manual Refresh**: Click the "Refresh Logs" button to reload immediately
- **Full-width Display**: Logs now display full-width for better readability

### Security

- Dashboard is only accessible from localhost (127.0.0.1, ::1, 172.16.0.0/12)
- IP-based access control prevents external access
- Never expose this endpoint in production environments