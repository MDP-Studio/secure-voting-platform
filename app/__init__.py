import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True, template_folder='templates')
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret'),
        SQLALCHEMY_DATABASE_URI= os.environ.get('DATABASE_URL') 
            or ('sqlite:///' + os.path.join(app.instance_path, 'app.db')),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

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

    # Add a single console handler once and reuse it. We mark the handler
    # with a private attribute so repeated create_app() calls won't add
    # duplicate handlers (which can leak memory and duplicate log lines).
    root_logger = logging.getLogger('')
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    if not any(getattr(h, '_is_app_console', False) for h in root_logger.handlers):
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(formatter)
        # marker used to detect this handler later
        setattr(console, '_is_app_console', True)
        root_logger.addHandler(console)
    else:
        # reuse existing app console handler
        console = next(h for h in root_logger.handlers if getattr(h, '_is_app_console', False))

    # Ensure werkzeug logs also use our console handler, but don't add it
    # twice if already present.
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.INFO)
    if not any(getattr(h, '_is_app_console', False) for h in werkzeug_logger.handlers):
        werkzeug_logger.addHandler(console)

    db.init_app(app)
    login_manager.init_app(app)

    # import blueprints (auth and main routes already in repo)
    from app import auth
    from app.routes import main, dev_routes, health
    app.register_blueprint(auth.auth)
    app.register_blueprint(main.main)
    app.register_blueprint(dev_routes.dev)
    app.register_blueprint(health.health)

    # create database tables if they don't exist
    with app.app_context():
        from app import models  # noqa: F401
        db.create_all()

    return app
