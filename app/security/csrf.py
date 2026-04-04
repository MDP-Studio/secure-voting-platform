"""
CSRF protection middleware.

Generates a per-session CSRF token and validates it on all POST/PUT/DELETE
requests. Uses itsdangerous for signed tokens — no extra dependencies.

Usage:
  - Call ``init_csrf(app)`` in the app factory
  - In templates: ``<input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">``
  - AJAX: read the token from a meta tag or cookie
"""

import secrets
from functools import wraps
from flask import session, request, abort, current_app


CSRF_TOKEN_KEY = '_csrf_token'
CSRF_FIELD_NAME = '_csrf_token'

# Endpoints that don't need CSRF (public APIs, health checks, etc.)
EXEMPT_ENDPOINTS = set()


def _get_csrf_token():
    """Get or create a per-session CSRF token."""
    if CSRF_TOKEN_KEY not in session:
        session[CSRF_TOKEN_KEY] = secrets.token_hex(32)
    return session[CSRF_TOKEN_KEY]


def _validate_csrf():
    """Validate CSRF token on state-changing requests."""
    if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
        return

    # Skip for testing
    if current_app.config.get('TESTING') or current_app.config.get('WTF_CSRF_ENABLED') is False:
        return

    # Skip exempt endpoints
    if request.endpoint in EXEMPT_ENDPOINTS:
        return

    # Skip API endpoints that use JSON content type (they're protected by
    # same-origin policy — browsers won't send JSON cross-origin without CORS)
    if request.content_type and 'application/json' in request.content_type:
        return

    token = request.form.get(CSRF_FIELD_NAME) or request.headers.get('X-CSRF-Token')
    expected = session.get(CSRF_TOKEN_KEY)

    if not token or not expected or not secrets.compare_digest(token, expected):
        abort(403)


def csrf_exempt(endpoint_name):
    """Mark an endpoint as CSRF-exempt."""
    EXEMPT_ENDPOINTS.add(endpoint_name)


def init_csrf(app):
    """Initialize CSRF protection on the app."""
    # Make csrf_token() available in all templates
    app.jinja_env.globals['csrf_token'] = _get_csrf_token

    # Validate on every request
    app.before_request(_validate_csrf)

    # Exempt specific endpoints
    csrf_exempt('results.verify_election_results')  # Public JSON API
    csrf_exempt('results.get_latest_results')        # Public GET (no side effects)
    csrf_exempt('health.healthz')
    csrf_exempt('health.ready')
    csrf_exempt('health.live')
    csrf_exempt('auth.login_nonce')
    csrf_exempt('otp.send_otp')  # Already requires authenticated session
    csrf_exempt('main.cast_anonymous_ballot')     # Anonymous endpoint (no cookies)
    csrf_exempt('main.blind_signing_public_key')  # Public GET
