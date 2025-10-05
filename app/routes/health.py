"""
Health check routes for monitoring and load balancer checks.
"""

from flask import Blueprint, jsonify
from app import db

health = Blueprint('health', __name__, url_prefix='/health')

@health.route('/healthz')
def healthz():
    """Basic health check endpoint for load balancers and monitoring."""
    return jsonify(status="ok")

@health.route('/ready')
def readiness():
    """Readiness probe - checks if the application is ready to serve requests."""
    try:
        # Check database connectivity
        db.session.execute(db.text('SELECT 1'))
        return jsonify(status="ready", database="connected")
    except Exception as e:
        return jsonify(status="not ready", database="disconnected", error=str(e)), 503

@health.route('/live')
def liveness():
    """Liveness probe - checks if the application is running."""
    return jsonify(status="alive")