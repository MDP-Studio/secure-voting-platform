"""Prometheus metrics helpers and /metrics endpoint.

This module exposes counters for security events and a small blueprint
to serve Prometheus metrics at /metrics. If prometheus_client is not
available, the counters degrade to no-op to avoid breaking the app.
"""
from flask import Blueprint, Response

metrics_bp = Blueprint('metrics', __name__)

try:
    from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

    login_nonce_failures = Counter(
        'login_nonce_failures_total', 'Number of login attempts with invalid/expired or missing nonce'
    )
    gotcha_triggers = Counter(
        'gotcha_triggers_total', 'Number of times honeypot gotcha field was populated'
    )
    turnstile_failures = Counter(
        'turnstile_verification_failures_total', 'Number of failed Cloudflare Turnstile verifications'
    )

    def metrics_response():
        return generate_latest(), CONTENT_TYPE_LATEST

except Exception:
    # prometheus_client not installed or failed to import; provide no-op
    class _NoopCounter:
        def inc(self, *a, **k):
            return None

    login_nonce_failures = _NoopCounter()
    gotcha_triggers = _NoopCounter()
    turnstile_failures = _NoopCounter()

    def metrics_response():
        return b"", 'text/plain'


@metrics_bp.route('/metrics')
def metrics():
    data, content_type = metrics_response()
    return Response(data, mimetype=content_type)
