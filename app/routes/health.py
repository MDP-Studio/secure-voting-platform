"""Minimal health endpoints for monitors and load balancers."""

from flask import Blueprint, current_app, jsonify

from app import db


health = Blueprint('health', __name__, url_prefix='/health')


@health.route('/healthz')
def healthz():
    """Return process health without runtime configuration details."""
    return jsonify(status='ok')


@health.route('/ready')
def readiness():
    """Check database readiness without returning internal diagnostics."""
    try:
        db.session.execute(db.text('SELECT 1'))
        return jsonify(status='ready', database='connected')
    except Exception:
        current_app.logger.exception('Readiness database probe failed')
        return jsonify(status='not ready', database='disconnected'), 503


@health.route('/live')
def liveness():
    """Return process liveness."""
    return jsonify(status='alive')
