import os
import sys
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail  

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
mail = Mail()   


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True, template_folder='templates')
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret'),
        SQLALCHEMY_DATABASE_URI= os.environ.get('DATABASE_URL') 
            or ('sqlite:///' + os.path.join(app.instance_path, 'app.db')),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,

        # Mail settings
        MAIL_SERVER=os.environ.get('MAIL_SERVER', 'smtp.gmail.com'),
        MAIL_PORT=int(os.environ.get('MAIL_PORT', 587)),
        MAIL_USE_TLS=True,
        MAIL_USE_SSL=False,
        MAIL_USERNAME=os.environ.get('MAIL_USERNAME'),
        MAIL_PASSWORD=os.environ.get('MAIL_PASSWORD'),
        MAIL_DEFAULT_SENDER=os.environ.get('MAIL_DEFAULT_SENDER') or os.environ.get('MAIL_USERNAME'),   
    )

    if test_config:
        app.config.update(test_config)

    # ensure instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    # Configure logging
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

    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)   # Initialize Mail

    # import blueprints (auth and main routes already in repo)
    from app import auth
    from app.routes import main, dev_routes, health
    from app.routes.otp import otp_bp   # Create OTP blueprint
    app.register_blueprint(auth.auth)
    app.register_blueprint(main.main)
    app.register_blueprint(dev_routes.dev)
    app.register_blueprint(health.health)
    app.register_blueprint(otp_bp)      # Register OTP blueprint

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
            user = User.query.get(int(user_id))
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
