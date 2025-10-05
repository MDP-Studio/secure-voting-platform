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

    # Configure logging
    log_file = os.path.join(app.instance_path, 'app.log')
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Also log to console (stdout)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console.setFormatter(formatter)
    # Add console handler to root logger
    logging.getLogger('').addHandler(console)

    # Ensure werkzeug logs also go to our handlers
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.INFO)
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
