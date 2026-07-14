import os
import sys
import logging
import types
from urllib.parse import urlsplit
from flask import Flask, g, current_app, has_request_context
import base64
from flask_sqlalchemy import SQLAlchemy
from flask_sqlalchemy.session import Session as FlaskSQLAlchemySession
from flask_login import LoginManager
from flask_mail import Mail  
from flask_migrate import Migrate
from sqlalchemy import event
from sqlalchemy.engine import Engine

from .security.encryption import ChaChaEncryptionService
from .utils.db_utils import _build_db_binds, get_database_url

class RoutingSession(FlaskSQLAlchemySession):
    """
    Route all ORM operations to a specific SQLAlchemy bind based on the
    current request's active user type. This enables using the exact same
    ORM models against multiple databases with identical schema.

    Strategy:
    - We set g._active_bind in a Flask before_request hook
      (e.g., 'admin' for managers and admin endpoints; 'voters' otherwise).
    - If no active bind is set, fall back to default engine.
    """

    def get_bind(  # type: ignore[override]
        self,
        mapper=None,
        clause=None,
        bind=None,
        **kwargs,
    ):
        if bind is not None:
            return bind
        if has_request_context():
            bind_name = getattr(g, "_active_bind", None)
            if bind_name:
                engine = self._db.engines.get(bind_name)
                if engine is None:
                    raise RuntimeError(
                        f"Configured database bind '{bind_name}' is unavailable."
                    )
                return engine
        return super().get_bind(
            mapper=mapper,
            clause=clause,
            bind=bind,
            **kwargs,
        )


class RoutingSQLAlchemy(SQLAlchemy):
    """SQLAlchemy extension configured with the request-aware session class."""


db = RoutingSQLAlchemy(session_options={"class_": RoutingSession})
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
mail = Mail()
migrate = Migrate()


def _env_bool(name, default):
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {'true', '1', 'yes', 'on'}:
        return True
    if normalized in {'false', '0', 'no', 'off'}:
        return False
    raise RuntimeError(f"{name} must be an explicit true or false value.")


def _normalize_public_origin(raw_value, *, require_https):
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise RuntimeError(
            "PUBLIC_BASE_URL is required outside test mode so security emails "
            "never depend on an untrusted request Host header."
        )
    parsed = urlsplit(raw_value.strip())
    if (
        parsed.scheme not in {'http', 'https'}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {'', '/'}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "PUBLIC_BASE_URL must be a bare http(s) origin without credentials, "
            "a path, query, or fragment."
        )
    if require_https and parsed.scheme != 'https':
        raise RuntimeError("Production requires an HTTPS PUBLIC_BASE_URL.")
    return f"{parsed.scheme}://{parsed.netloc}", parsed.hostname.lower()


def _parse_trusted_hosts(raw_value, public_hostname):
    if isinstance(raw_value, str):
        hosts = [item.strip().lower() for item in raw_value.split(',') if item.strip()]
    elif isinstance(raw_value, (list, tuple)):
        hosts = [str(item).strip().lower() for item in raw_value if str(item).strip()]
    elif raw_value is None:
        hosts = []
    else:
        raise RuntimeError("TRUSTED_HOSTS must be a comma-separated host allowlist.")

    if not hosts:
        hosts = [public_hostname]
        if public_hostname == 'localhost':
            hosts.append('127.0.0.1')
    for host in hosts:
        candidate = host[1:] if host.startswith('.') else host
        if not candidate or '://' in host or '/' in host or any(ch.isspace() for ch in host):
            raise RuntimeError(
                "TRUSTED_HOSTS entries must contain hostnames only, without schemes or paths."
            )
    public_host_is_trusted = any(
        host == public_hostname
        or (
            host.startswith('.')
            and (
                public_hostname == host[1:]
                or public_hostname.endswith(host)
            )
        )
        for host in hosts
    )
    if not public_host_is_trusted:
        raise RuntimeError(
            "TRUSTED_HOSTS must include the hostname from PUBLIC_BASE_URL."
        )
    return hosts


def _validate_delivery_config(app, production_like):
    if app.config.get('TESTING'):
        return
    required = {
        'MAIL_SERVER': app.config.get('MAIL_SERVER'),
        'MAIL_USERNAME': app.config.get('MAIL_USERNAME'),
        'MAIL_PASSWORD': app.config.get('MAIL_PASSWORD'),
        'MAIL_DEFAULT_SENDER': app.config.get('MAIL_DEFAULT_SENDER'),
    }
    for name, value in required.items():
        if (
            not isinstance(value, str)
            or not value.strip()
            or value.strip().upper().startswith(('CHANGE_ME', 'REPLACE_', 'YOUR-'))
        ):
            raise RuntimeError(
                f"{name} is required outside test mode because account verification "
                "and password recovery depend on email delivery."
            )
    if '@' not in app.config['MAIL_DEFAULT_SENDER']:
        raise RuntimeError("MAIL_DEFAULT_SENDER must be a valid email address.")
    if app.config.get('MAIL_USE_TLS') and app.config.get('MAIL_USE_SSL'):
        raise RuntimeError("MAIL_USE_TLS and MAIL_USE_SSL cannot both be enabled.")
    port = app.config.get('MAIL_PORT')
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise RuntimeError("MAIL_PORT must be an integer from 1 to 65535.")
    if production_like:
        if not (app.config.get('MAIL_USE_TLS') or app.config.get('MAIL_USE_SSL')):
            raise RuntimeError("Production SMTP requires TLS or SSL.")
        if not app.config.get('ENABLE_MFA'):
            raise RuntimeError("Production requires ENABLE_MFA=true.")

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:
        logging.getLogger(__name__).debug("Handled exception in app/__init__.py", exc_info=True)
        pass

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True, template_folder='templates')
    
    # register blueprints and other stuff here
    # default config
    # Check if running in testing mode (from DEPLOYMENT_ENV or FLASK_ENV)
    deployment_env = os.environ.get('DEPLOYMENT_ENV', '').strip().lower()
    flask_env = os.environ.get('FLASK_ENV', '').strip().lower()
    allowed_deployment_environments = {
        '',
        'development',
        'local',
        'local-demo',
        'testing',
        'staging',
        'prod',
        'production',
    }
    allowed_flask_environments = {
        '',
        'development',
        'testing',
        'staging',
        'production',
    }
    if deployment_env not in allowed_deployment_environments:
        raise RuntimeError(f"Unsupported DEPLOYMENT_ENV: {deployment_env!r}")
    if flask_env not in allowed_flask_environments:
        raise RuntimeError(f"Unsupported FLASK_ENV: {flask_env!r}")
    deployment_is_production_like = deployment_env in {
        'prod',
        'production',
        'staging',
    }
    flask_is_production_like = flask_env in {'production', 'staging'}
    if (
        deployment_env
        and flask_env
        and deployment_is_production_like != flask_is_production_like
    ):
        raise RuntimeError(
            "DEPLOYMENT_ENV and FLASK_ENV describe conflicting security modes."
        )
    explicit_environment = deployment_env or flask_env
    # An unspecified environment is hosted by default. Local/test relaxations
    # require an explicit recognized mode, never absence of configuration.
    production_like = (
        deployment_is_production_like
        or flask_is_production_like
        or not explicit_environment
    )
    is_testing = (
        not production_like
        and (deployment_env == 'testing' or flask_env == 'testing')
    )
    is_local_development = (
        deployment_env in {'development', 'local', 'local-demo'}
        or flask_env == 'development'
    )
    cookie_secure_env = os.environ.get('SESSION_COOKIE_SECURE')
    if cookie_secure_env is None:
        session_cookie_secure = not (is_testing or is_local_development)
    else:
        normalized_cookie_setting = cookie_secure_env.strip().lower()
        if normalized_cookie_setting in {'true', '1', 'yes', 'on'}:
            session_cookie_secure = True
        elif normalized_cookie_setting in {'false', '0', 'no', 'off'}:
            session_cookie_secure = False
        else:
            raise RuntimeError(
                "SESSION_COOKIE_SECURE must be an explicit true or false value."
            )
    
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
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        AUDIT_HMAC_KEY=os.environ.get('AUDIT_HMAC_KEY'),
        SQLALCHEMY_DATABASE_URI=get_database_url(app.instance_path),
        # Optional secondary databases (binds). If not provided, they default
        # to the primary URI so the app keeps working unchanged.
        SQLALCHEMY_BINDS=_build_db_binds(app.instance_path),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        # The application has no upload feature. Bound every request body to
        # reduce anonymous parser and hashing exposure at the Flask boundary.
        MAX_CONTENT_LENGTH=64 * 1024,
        
        # Enable TESTING mode when running in test environment
        # This disables security checks like login nonce requirement for easier testing
        TESTING=is_testing,

        # Mail settings
        MAIL_SERVER=os.environ.get('MAIL_SERVER', 'smtp.gmail.com'),
        MAIL_PORT=int(os.environ.get('MAIL_PORT', 587)),
        MAIL_USE_TLS=_env_bool('MAIL_USE_TLS', True),
        MAIL_USE_SSL=_env_bool('MAIL_USE_SSL', False),
        MAIL_USERNAME=os.environ.get('MAIL_USERNAME'),
        MAIL_PASSWORD=os.environ.get('MAIL_PASSWORD'),
        MAIL_DEFAULT_SENDER=os.environ.get('MAIL_DEFAULT_SENDER') or os.environ.get('MAIL_USERNAME'),
        PUBLIC_BASE_URL=os.environ.get('PUBLIC_BASE_URL'),
        TRUSTED_HOSTS=os.environ.get('TRUSTED_HOSTS'),

        # Result-signing Vault identity. VAULT_CLUSTER_ID is a stable,
        # non-secret deployment identifier used in persisted provenance.
        VAULT_ADDR=os.environ.get('VAULT_ADDR'),
        VAULT_CLUSTER_ID=os.environ.get('VAULT_CLUSTER_ID'),
        VAULT_NAMESPACE=os.environ.get('VAULT_NAMESPACE', ''),
        VAULT_MOUNT=os.environ.get('VAULT_MOUNT', 'transit'),
        VAULT_TRANSIT_KEY=os.environ.get('VAULT_TRANSIT_KEY', 'results-signing'),

        # MFA settings
        ENABLE_MFA=_env_bool('ENABLE_MFA', False),

        # Proxy settings for running behind nginx
        SESSION_COOKIE_NAME='otp_session',  # Rename session cookie for clarity
        # Fail safe for any hosted/unspecified environment. Local HTTP demos
        # must opt into a recognized development environment or explicitly
        # set SESSION_COOKIE_SECURE=false.
        SESSION_COOKIE_SECURE=session_cookie_secure,
        SESSION_COOKIE_SAMESITE='Lax',

        # Optional: when true, add X-DB-Bind header to responses to show which
        # database bind handled the request (useful for verifying split routing)
        DEBUG_DB_BIND=os.environ.get('DEBUG_DB_BIND', 'false').lower() in ('true','1','yes'),
    )

    # Trust proxy headers when running behind nginx
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

    if test_config:
        app.config.update(test_config)
    if (
        cookie_secure_env is None
        and not (test_config and 'SESSION_COOKIE_SECURE' in test_config)
    ):
        app.config['SESSION_COOKIE_SECURE'] = not (
            app.config.get('TESTING') or is_local_development
        )
    if (
        production_like
        and not app.config.get('SESSION_COOKIE_SECURE')
    ):
        raise RuntimeError(
            "Production requires SESSION_COOKIE_SECURE=true and HTTPS."
        )

    key_b64 = os.environ.get("VOTER_PII_KEY_BASE64")
    if not key_b64 and app.config.get('TESTING'):
        key_b64 = base64.b64encode(os.urandom(32)).decode('ascii')
        os.environ['VOTER_PII_KEY_BASE64'] = key_b64
    if not key_b64:
        raise RuntimeError(
            "VOTER_PII_KEY_BASE64 is required outside test mode and must remain stable."
        )
    try:
        decoded_key = base64.b64decode(key_b64, validate=True)
    except Exception as exc:
        raise RuntimeError(
            "VOTER_PII_KEY_BASE64 is not valid Base64 encoding."
        ) from exc
    if len(decoded_key) != 32:
        raise RuntimeError(
            "VOTER_PII_KEY_BASE64 must decode to exactly 32 bytes for "
            "ChaCha20-Poly1305."
        )

    if not app.config.get('TESTING'):
        required_secrets = {
            'SECRET_KEY': app.config.get('SECRET_KEY'),
            'LICENSE_HASH_PEPPER': os.environ.get('LICENSE_HASH_PEPPER'),
            'AUDIT_HMAC_KEY': app.config.get('AUDIT_HMAC_KEY'),
        }
        for name, value in required_secrets.items():
            if (
                not isinstance(value, str)
                or len(value) < 32
                or value.upper().startswith(('CHANGE_ME', 'REPLACE_'))
            ):
                raise RuntimeError(
                    f"{name} must be an explicit non-placeholder value of at least 32 characters."
                )

    public_base_url = app.config.get('PUBLIC_BASE_URL')
    if app.config.get('TESTING') and not public_base_url:
        public_base_url = 'http://localhost'
    normalized_origin, public_hostname = _normalize_public_origin(
        public_base_url,
        require_https=production_like,
    )
    app.config['PUBLIC_BASE_URL'] = normalized_origin
    app.config['TRUSTED_HOSTS'] = _parse_trusted_hosts(
        app.config.get('TRUSTED_HOSTS'),
        public_hostname,
    )
    _validate_delivery_config(app, production_like)

    ChaChaEncryptionService.initialize(key_b64)

    # In test mode, avoid external DB connections; point binds to the default URI
    # so the extension has engines for any bind keys encountered.
    if app.config.get('TESTING'):
        default_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
        app.config['SQLALCHEMY_BINDS'] = {
            'admin': default_uri,
            'voters': default_uri,
        }

    # ensure instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        logging.getLogger(__name__).debug("Handled exception in app/__init__.py", exc_info=True)
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

    # Initialize audit/HMAC-backed logging (writes to instance/audit.log by default)
    try:
        from app.logging_service import init_audit_logging
        init_audit_logging(app)
    except Exception:
        app.logger.exception("Failed to initialize audit logging")
        if not app.config.get('TESTING'):
            raise

    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)   # Initialize Mail

    try:
        migrate.init_app(app, db)
    except Exception as e:
        app.logger.warning(f"Flask-Migrate initialization failed: {e}")

    # CSRF protection
    from app.security.csrf import init_csrf
    init_csrf(app)

    # import blueprints (auth and main routes already in repo)
    from app import auth
    from app.routes import main, health, candidates, registration, password, results
    from app.routes.metrics import metrics_bp
    from app.routes.password_reset import password_reset_bp
    from app.routes.elections import elections_bp
    from app.routes.audit import audit_bp
    app.register_blueprint(auth.auth)
    app.register_blueprint(main.main)
    if not production_like and (app.config.get('TESTING') or is_local_development):
        from app.routes import dev_routes

        app.register_blueprint(dev_routes.dev)
    app.register_blueprint(health.health)
    app.register_blueprint(candidates.candidates)
    app.register_blueprint(registration.registration)
    app.register_blueprint(results.results)
    app.register_blueprint(password.password_bp)
    app.register_blueprint(password_reset_bp)
    app.register_blueprint(elections_bp)
    app.register_blueprint(audit_bp)

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

    # Register error handlers
    from flask import render_template as _rt

    @app.errorhandler(404)
    def not_found(e):
        return _rt('errors/404.html'), 404

    @app.errorhandler(403)
    def forbidden(e):
        return _rt('errors/403.html'), 403

    @app.errorhandler(500)
    def server_error(e):
        return _rt('errors/500.html'), 500

    # Route database operations to a bind based on user type and path
    @app.before_request
    def _select_db_bind_for_request():
        """
        Load request identity through the least-privileged voter credential,
        then elevate database access only for an authenticated manager or
        delegate. The primary engine is reserved for migrations/startup and
        must never be used as an implicit request fallback.
        """
        try:
            # If no binds configured (e.g., testing), do nothing
            if not current_app.config.get('SQLALCHEMY_BINDS'):
                g._active_bind = None
                return
            # Set the least-privileged bind before touching current_user.
            # Flask-Login resolves current_user lazily and its user_loader runs
            # an ORM query, so choosing the bind afterwards would expose the
            # primary migration credential to normal request traffic.
            g._active_bind = 'voters'
            # Production identity is established later from the authoritative
            # JWT. Tests retain Flask-Login session compatibility so existing
            # unit fixtures can exercise route authorization without cookies.
            if current_app.config.get('TESTING'):
                from flask_login import current_user
                if getattr(current_user, 'is_authenticated', False):
                    if (
                        getattr(current_user, 'is_manager', False)
                        or getattr(current_user, 'is_delegate', False)
                    ):
                        g._active_bind = 'admin'
        except Exception:
            # Never fall through to the primary migration credential on a
            # routing error. The voter account is the least-privilege fallback.
            logging.getLogger(__name__).warning(
                "Database bind selection failed; using the voter bind.",
                exc_info=True,
            )
            g._active_bind = 'voters'

    # Create database tables if they don't exist (Flask-SQLAlchemy will
    # handle creating tables for the default and any configured binds).
    # Blind-signing keys are generated only during an election's transition to
    # open. A process-global key here would destroy election binding.
    with app.app_context():
        # In testing, disable Vote.__bind_key__ so Vote shares the default metadata
        if app.config.get('TESTING'):
            os.environ['DISABLE_VOTE_BIND'] = '1'
        from app import models  # noqa: F401  # agent-quality: allow: import registers model metadata for tests
        # In testing, collapse all per-bind tables into the default metadata
        # so foreign keys resolve within a single SQLite database. Let tests
        # call db.create_all() themselves (tests/conftest.py already does this)
        # to avoid duplicate DDL and to ensure their engine/URI is used.
        if app.config.get('TESTING'):
            try:
                # 1) Remove bind_key markers from tables on the default metadata
                for tbl in list(db.metadata.tables.values()):
                    tbl.info.pop('bind_key', None)

                # 2) Move any tables that were created on per-bind metadatas
                #    into the default metadata (should be none after disabling
                #    Vote bind, but keep for safety)
                for key, meta in list(db.metadatas.items()):
                    if key is None:
                        continue
                    for t in list(meta.tables.values()):
                        if t.key not in db.metadata.tables:
                            t.tometadata(db.metadata)
                    meta.tables.clear()

                # 3) Replace the extension's metadatas registry with only the default
                try:
                    db.metadatas.clear()
                    db.metadatas[None] = db.metadata
                except Exception:
                    logging.getLogger(__name__).debug("Handled exception in app/__init__.py", exc_info=True)
                    pass

                # 4) Monkey-patch create_all to operate only on the default
                #    metadata/engine in testing to avoid extension bind logic.
                def _testing_call_for_binds(self, bind_key, op_name: str):
                    getattr(self.metadata, op_name)(bind=self.engine)
                db._call_for_binds = types.MethodType(_testing_call_for_binds, db)
            except Exception:
                logging.getLogger(__name__).debug("Handled exception in app/__init__.py", exc_info=True)
                pass
        else:
            # Avoid implicit schema creation unless explicitly requested.
            # This prevents accidental external DB connections when modules/tests
            # import the app without providing TESTING config early enough.
            auto_create = str(os.environ.get('AUTO_CREATE_ALL', '0')).lower() in ('1','true','yes')
            if auto_create:
                db.create_all()

    # NOTE: older code paths may expect a Flask-Login user; we enhance request
    # processing by checking for a JWT session_token cookie and loading the
    # corresponding user for the request. This implements a signed, short-lived
    # session with sliding expiration.
    from flask import request, current_app, g, redirect, url_for, session
    from flask_login import login_user, logout_user
    from app.security.jwt_helpers import decode_token, issue_token
    from app.models import User

    @app.before_request
    def _load_user_from_jwt():
        if request.endpoint == 'main.cast_anonymous_ballot':
            # The ballot-submission phase is identity-free even if a caller
            # accidentally attaches a valid voter, delegate, or manager
            # cookie. Do not decode or refresh the bearer token, do not expose
            # Flask-Login identity, and always use the least-privileged ballot
            # credential.
            g._active_bind = 'voters'
            g._login_user = current_app.login_manager.anonymous_user()
            return None

        def reject_session_token():
            logout_user()
            # A presented but invalid/revoked bearer token invalidates the
            # compatibility session wholesale. This prevents stale Flask-Login
            # state or MFA state from surviving token rejection.
            session.clear()
            g._clear_session_token = True
            g._clear_flask_session_cookie = True

        token = request.cookies.get('session_token')
        if not token:
            if (
                not current_app.config.get('TESTING')
                and session.get('_user_id') is not None
            ):
                # A Flask-Login identity without the authoritative JWT is a
                # downgrade attempt. Anonymous session state, including flash
                # messages and the pre-auth MFA handoff, is not authenticated
                # state and must remain available across normal requests.
                reject_session_token()
            return None

        payload = decode_token(token)
        if not payload:
            reject_session_token()
            return None

        user_id = payload.get('sub')
        try:
            user = db.session.get(User, int(user_id))
        except Exception:
            logging.getLogger(__name__).debug("Handled exception in app/__init__.py", exc_info=True)
            reject_session_token()
            return None

        token_version = payload.get('ver')
        if (
            user is None
            or (user.account_status or '').lower() == 'rejected'
            or isinstance(token_version, bool)
            or not isinstance(token_version, int)
            or token_version != user.session_version
        ):
            reject_session_token()
            return None

        if user:
            # Block expired-password users from continuing — force password change
            if user.is_password_expired() and request.endpoint not in (
                'password.change_password', 'auth.logout', 'static'
            ):
                login_user(user, remember=False)
                from flask import flash
                flash('Your password has expired. Please change it to continue.', 'warning')
                return redirect(url_for('password.change_password'))

            login_user(user, remember=False)
            g._active_bind = (
                'admin'
                if getattr(user, 'is_manager', False)
                or getattr(user, 'is_delegate', False)
                else 'voters'
            )

            # sliding expiration: refresh if less than half lifetime remains
            import time
            now = int(time.time())
            iat = payload.get('iat', now)
            exp = payload.get('exp', now)
            lifetime = exp - iat
            if lifetime > 0 and (exp - now) < (lifetime // 2):
                # Only refresh if password is still valid
                if not user.is_password_expired():
                    g._new_session_token = issue_token(
                        user.id,
                        user.session_version,
                    )

        return None

    @app.after_request
    def _maybe_set_refresh_cookie(response):
        if getattr(g, '_clear_flask_session_cookie', False):
            response.delete_cookie(
                current_app.config.get('SESSION_COOKIE_NAME', 'session'),
                secure=bool(current_app.config.get('SESSION_COOKIE_SECURE')),
                samesite=current_app.config.get('SESSION_COOKIE_SAMESITE', 'Lax'),
            )
        if getattr(g, '_clear_session_token', False):
            response.delete_cookie('session_token')
        new_token = getattr(g, '_new_session_token', None)
        if new_token:
            secure = bool(int(current_app.config.get('SESSION_COOKIE_SECURE', 0)))
            samesite = current_app.config.get('SESSION_COOKIE_SAMESITE', 'Lax')
            response.set_cookie('session_token', new_token, httponly=True, secure=secure, samesite=samesite)
        # Optionally expose the active DB bind for verification during development
        if current_app.config.get('DEBUG_DB_BIND'):
            bind_name = getattr(g, '_active_bind', None)
            response.headers['X-DB-Bind'] = bind_name or 'default'
        return response

    return app
