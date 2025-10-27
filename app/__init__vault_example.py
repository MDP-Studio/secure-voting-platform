"""
Example of how to update app/__init__.py to use Vault-based configuration.

This is an example file showing how to integrate Vault configuration
into the existing Flask application. Copy the relevant parts to app/__init__.py
to enable Vault-based secrets management.
"""

import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from werkzeug.middleware.proxy_fix import ProxyFix

# Import Vault configuration
from .vault_config import create_vault_config, vault_health_check, get_secret_key, get_database_url, get_mail_config, get_security_config

# ... existing imports ...

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()

# ... existing event listeners ...

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True, template_folder='templates')

    # Load configuration from Vault with fallback to environment variables
    vault_config = create_vault_config()
    
    # Default configuration with Vault integration
    app.config.from_mapping(
        # Core Flask configuration
        SECRET_KEY=get_secret_key(),
        SQLALCHEMY_DATABASE_URI=get_database_url() or ('sqlite:///' + os.path.join(app.instance_path, 'app.db')),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,

        # Mail configuration from Vault
        **get_mail_config(),

        # Security configuration from Vault
        **get_security_config(),

        # Session configuration
        SESSION_COOKIE_NAME='otp_session',
        SESSION_COOKIE_SECURE=False,  # Set to True in production with HTTPS
        SESSION_COOKIE_SAMESITE='Lax',
    )

    # Trust proxy headers when running behind nginx
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

    # Apply test configuration if provided
    if test_config:
        app.config.update(test_config)

    # Ensure instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    # Configure logging
    log_file = os.path.join(app.instance_path, 'app.log')
    logging.basicConfig(
        filename=log_file,
        level=getattr(logging, app.config.get('LOG_LEVEL', 'INFO')),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)

    # Configure login manager
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'

    # Register blueprints
    from .routes import main, auth, password, otp, registration, candidates, results, admin_users, health, metrics, dev_routes
    from .security import vault_client

    app.register_blueprint(main.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(password.password_bp)
    app.register_blueprint(otp.otp_bp)
    app.register_blueprint(registration.registration_bp)
    app.register_blueprint(candidates.candidates_bp)
    app.register_blueprint(results.results_bp)
    app.register_blueprint(admin_users.admin_bp)
    app.register_blueprint(health.health)
    app.register_blueprint(metrics.metrics_bp)
    app.register_blueprint(dev_routes.dev)

    # Add Vault health check endpoint
    @app.route('/vault-health')
    def vault_health():
        """Vault health check endpoint."""
        is_healthy, message = vault_health_check()
        return {
            'status': 'healthy' if is_healthy else 'unhealthy',
            'message': message,
            'vault_enabled': vault_client.is_enabled
        }

    # Add comprehensive health check endpoint
    @app.route('/health')
    def health():
        """Comprehensive health check including Vault."""
        vault_healthy, vault_message = vault_health_check()
        
        # Check database connectivity
        try:
            with app.app_context():
                db.session.execute(db.text('SELECT 1'))
            db_healthy = True
            db_message = "Database connected"
        except Exception as e:
            db_healthy = False
            db_message = f"Database error: {str(e)}"
        
        overall_healthy = vault_healthy and db_healthy
        
        return {
            'status': 'healthy' if overall_healthy else 'unhealthy',
            'timestamp': __import__('datetime').datetime.utcnow().isoformat(),
            'vault': {
                'status': 'healthy' if vault_healthy else 'unhealthy',
                'message': vault_message,
                'enabled': vault_client.is_enabled
            },
            'database': {
                'status': 'healthy' if db_healthy else 'unhealthy',
                'message': db_message
            }
        }

    # Initialize database
    with app.app_context():
        db.create_all()
        
        # Initialize Vault if available
        if vault_client.is_enabled:
            try:
                # Test Vault connectivity
                is_healthy, message = vault_health_check()
                if is_healthy:
                    logging.info("Vault integration initialized successfully")
                else:
                    logging.warning(f"Vault integration warning: {message}")
            except Exception as e:
                logging.error(f"Vault integration failed: {e}")

    return app
