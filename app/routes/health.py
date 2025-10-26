"""
Health check routes for monitoring and load balancer checks.
"""

from flask import Blueprint, jsonify, current_app
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
        testing_mode = current_app.config.get('TESTING', False)
        mode_str = "🧪 TESTING" if testing_mode else "🔒 PRODUCTION"
        return jsonify(
            status="ready", 
            database="connected",
            mode=mode_str,
            testing=testing_mode
        )
    except Exception as e:
        return jsonify(status="not ready", database="disconnected", error=str(e)), 503

@health.route('/live')
def liveness():
    """Liveness probe - checks if the application is running."""
    return jsonify(status="alive")