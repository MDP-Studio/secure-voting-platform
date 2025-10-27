import os
import sys
import logging
import base64
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail  
from flask_migrate import Migrate
from sqlalchemy import event
from sqlalchemy.engine import Engine
from .security.encryption import ChaChaEncryptionService

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
mail = Mail()
migrate = Migrate()

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:
        pass

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True, template_folder='templates')
    
    # Generate a new key if not exists (development only)
    if not os.environ.get('VOTER_PII_KEY_BASE64'):
        # Generate a random 32-byte key and encode it in base64
        key = base64.b64encode(os.urandom(32))
        os.environ['VOTER_PII_KEY_BASE64'] = key.decode()
        app.logger.warning("Generated new encryption key: %s", key.decode())
    
    ChaChaEncryptionService.initialize(os.environ.get('VOTER_PII_KEY_BASE64'))
    # register blueprints and other stuff here
    # default config
    # Check if running in testing mode (from DEPLOYMENT_ENV or FLASK_ENV)
    deployment_env = os.environ.get('DEPLOYMENT_ENV', '').lower()
    flask_env = os.environ.get('FLASK_ENV', '').lower()
    is_testing = deployment_env == 'testing' or flask_env == 'testing'
    
    # Log testing mode for debugging
    logging.info(f"🧪 DEPLOYMENT_ENV={deployment_env}, FLASK_ENV={flask_env}, TESTING={is_testing}")
    if is_testing:
        logging.info("✅ Testing mode ENABLED - security checks disabled")
    else:
        logging.info("🔒 Production mode - security checks enabled")
    
    # Log environment detection for debugging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.info(f"🔍 Environment Detection:")
    logger.info(f"  DEPLOYMENT_ENV={deployment_env or '(not set)'}")
    logger.info(f"  FLASK_ENV={flask_env or '(not set)'}")
    logger.info(f"  → Testing Mode Enabled: {is_testing}")
    
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret'),
        SQLALCHEMY_DATABASE_URI= os.environ.get('DATABASE_URL') 
            or ('sqlite:///' + os.path.join(app.instance_path, 'app.db')),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        
        # Enable TESTING mode when running in test environment
        # This disables security checks like login nonce requirement for easier testing
        TESTING=is_testing,

        # Mail settings
        MAIL_SERVER=os.environ.get('MAIL_SERVER', 'smtp.gmail.com'),
        MAIL_PORT=int(os.environ.get('MAIL_PORT', 587)),
        MAIL_USE_TLS=True,
        MAIL_USE_SSL=False,
        MAIL_USERNAME=os.environ.get('MAIL_USERNAME'),
        MAIL_PASSWORD=os.environ.get('MAIL_PASSWORD'),
        MAIL_DEFAULT_SENDER=os.environ.get('MAIL_DEFAULT_SENDER') or os.environ.get('MAIL_USERNAME'),

        # MFA settings
        ENABLE_MFA=os.environ.get('ENABLE_MFA', 'False').lower() in ('true', '1', 'yes'),

        # Proxy settings for running behind nginx
        SESSION_COOKIE_NAME='otp_session',  # Rename session cookie for clarity
        SESSION_COOKIE_SECURE=False,  # Set to True in production with HTTPS
        SESSION_COOKIE_SAMESITE='Lax',
    )

    key_b64 = os.environ.get("VOTER_PII_KEY_BASE64")
    if not key_b64:
        raise RuntimeError("Missing VOTER_PII_KEY_BASE64 in environment.")

    try:
        decoded_key = base64.b64decode(key_b64)
    except Exception:
        raise RuntimeError("VOTER_PII_KEY_BASE64 is not valid Base64 encoding.")

    if len(decoded_key) != 32:
        raise RuntimeError("VOTER_PII_KEY_BASE64 must decode to exactly 32 bytes for AES-256.")

    # Trust proxy headers when running behind nginx
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

    if test_config:
        app.config.update(test_config)

    # ensure instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    # Configure logging (avoid adding duplicate handlers if the app is
    # created multiple times in the same process — e.g. during tests)
    log_file = os.path.join(app.instance_path, 'app.log')
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Also log to console (stdout). Name the handler and only add it once
    console = logging.StreamHandler(stream=sys.stdout)
    console.name = 'app_console'
    console.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console.setFormatter(formatter)

    root_logger = logging.getLogger('')
    # Add console handler to root logger only if not already present
    if not any(getattr(h, 'name', None) == 'app_console' for h in root_logger.handlers):
        root_logger.addHandler(console)

    # Ensure werkzeug logs also go to our handlers, avoid duplicate handlers
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.INFO)
    if not any(getattr(h, 'name', None) == 'app_console' for h in werkzeug_logger.handlers):
        werkzeug_logger.addHandler(console)

    # Import middleware and register geo-ip check after logging is set up
    from .middleware import check_geo_ip
    app.before_request(check_geo_ip)

    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)   # Initialize Mail

    # import blueprints (auth and main routes already in repo)
    from app import auth
    from app.routes import main, dev_routes, health, candidates, registration, password, results
    from app.routes.otp import otp_bp   # Create OTP blueprint
    from app.routes.metrics import metrics_bp
    app.register_blueprint(auth.auth)
    app.register_blueprint(main.main)
    app.register_blueprint(dev_routes.dev)
    app.register_blueprint(health.health)
    app.register_blueprint(candidates.candidates)
    app.register_blueprint(registration.registration)
    app.register_blueprint(results.results)
    app.register_blueprint(otp_bp)      # Register OTP blueprint
    app.register_blueprint(password.password_bp)  # Register password management blueprint

    # expose Prometheus metrics at /metrics (metrics blueprint is optional)
    try:
        app.register_blueprint(metrics_bp, url_prefix="/metrics")
    except Exception:
        app.logger.debug('metrics blueprint not registered')

    try:
        from app.routes.admin_users import admin_bp
        app.register_blueprint(admin_bp, url_prefix="/admin")
    except Exception as e:
        app.logger.warning(f"Admin users blueprint not loaded: {e}")


    # create database tables if they don't exist
    with app.app_context():
        from app import models  # noqa: F401
        db.create_all()

    # NOTE: older code paths may expect a Flask-Login user; we enhance request
    # processing by checking for a JWT session_token cookie and loading the
    # corresponding user for the request. This implements a signed, short-lived
    # session with sliding expiration.
    from flask import request, current_app, g
    from flask_login import login_user
    from app.security.jwt_helpers import decode_token, issue_token
    from app.models import User

    @app.before_request
    def _load_user_from_jwt():
        token = request.cookies.get('session_token')
        if not token:
            return None

        payload = decode_token(token)
        if not payload:
            return None

        user_id = payload.get('sub')
        try:
            user = db.session.get(User, int(user_id))
        except Exception:
            return None

        if user:
            login_user(user, remember=False)

            # sliding expiration: refresh if less than half lifetime remains
            import time
            now = int(time.time())
            iat = payload.get('iat', now)
            exp = payload.get('exp', now)
            lifetime = exp - iat
            if lifetime > 0 and (exp - now) < (lifetime // 2):
                # Defer cookie setting to a single global after_request by storing
                # the new token on flask.g for this request.
                g._new_session_token = issue_token(user.id)

        return None

    @app.after_request
    def _maybe_set_refresh_cookie(response):
        new_token = getattr(g, '_new_session_token', None)
        if new_token:
            secure = bool(int(current_app.config.get('SESSION_COOKIE_SECURE', 0)))
            samesite = current_app.config.get('SESSION_COOKIE_SAMESITE', 'Lax')
            response.set_cookie('session_token', new_token, httponly=True, secure=secure, samesite=samesite)
        return response

    return app
