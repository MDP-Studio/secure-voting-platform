import logging
import os
import time

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url


def _validated_database_secret(name, value):
    """Reject missing, placeholder, or trivially weak database credentials."""
    if (
        not isinstance(value, str)
        or len(value) < 16
        or value.upper().startswith(("CHANGE_ME", "REPLACE_"))
    ):
        raise RuntimeError(
            f"{name} must be an explicit non-placeholder value of at least 16 characters"
        )
    return value


def get_database_url(instance_path):
    """Return an explicit URL or safely build one from discrete MySQL fields."""
    explicit = os.environ.get('DATABASE_URL')
    if explicit:
        parsed = make_url(explicit)
        if parsed.get_backend_name() == 'mysql':
            _validated_database_secret('DATABASE_URL password', parsed.password)
        return explicit
    host = os.environ.get('DB_HOST')
    if host:
        required = {
            'MYSQL_USER': os.environ.get('MYSQL_USER'),
            'MYSQL_PASSWORD': os.environ.get('MYSQL_PASSWORD'),
            'MYSQL_DATABASE': os.environ.get('MYSQL_DATABASE'),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(
                "Missing primary database configuration: " + ", ".join(missing)
            )
        password = _validated_database_secret(
            'MYSQL_PASSWORD',
            required['MYSQL_PASSWORD'],
        )
        return URL.create(
            'mysql+pymysql',
            username=required['MYSQL_USER'],
            password=password,
            host=host,
            port=int(os.environ.get('DB_PORT', '3306')),
            database=required['MYSQL_DATABASE'],
        ).render_as_string(hide_password=False)
    return 'sqlite:///' + os.path.join(instance_path, 'app.db')


def wait_for_db(max_attempts=30, delay=2):
    """Wait for the database to be ready with timeout."""
    from flask import current_app, has_app_context

    db_url = (
        current_app.config['SQLALCHEMY_DATABASE_URI']
        if has_app_context()
        else get_database_url(os.path.join(os.path.dirname(__file__), '..', 'instance'))
    )
    print("⏳ Waiting for database to be ready...")
    engine = create_engine(db_url)
    attempts = 0
    while attempts < max_attempts:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                # Try to get database name (works for MySQL, not SQLite)
                try:
                    result = conn.execute(text("SELECT DATABASE()")).fetchone()
                    db_name = result[0] if result else "unknown"
                except:
                    logging.getLogger(__name__).debug("Handled exception in app/utils/db_utils.py", exc_info=True)
                    db_name = "SQLite" if db_url.startswith("sqlite") else "unknown"
                print(f"✅ Database '{db_name}' is ready!")
            break
        except Exception as e:
            attempts += 1
            if attempts >= max_attempts:
                print(f"❌ Database not ready after {max_attempts} attempts: {e}")
                raise
            print(f"Database not ready (attempt {attempts}/{max_attempts}): {e}. Retrying in {delay} seconds...")
            time.sleep(delay)
    engine.dispose()


def _build_bind_url(base_url, user, password, db_name):
    """Build a database URL by replacing user, password, and db in base_url."""
    return make_url(base_url).set(
        username=user,
        password=password,
        database=db_name,
    ).render_as_string(hide_password=False)


def _build_db_binds(instance_path):
    """Build database bind URLs dynamically from DATABASE_URL and credentials."""
    base_url = get_database_url(instance_path)
    
    # For SQLite, binds don't apply (single file), so use the same URL
    if base_url.startswith('sqlite'):
        return {
            'admin': base_url,
            'voters': base_url,
        }
    
    # For other DBs, build URLs with different credentials and DB names
    admin_user = os.environ.get('VOTING_ADMIN_USER')
    admin_pass = os.environ.get('VOTING_ADMIN_PASS')
    voter_user = os.environ.get('VOTING_VOTER_USER')
    voter_pass = os.environ.get('VOTING_VOTER_PASS')
    missing = [
        name
        for name, value in (
            ('VOTING_ADMIN_USER', admin_user),
            ('VOTING_ADMIN_PASS', admin_pass),
            ('VOTING_VOTER_USER', voter_user),
            ('VOTING_VOTER_PASS', voter_pass),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing split-database credentials: " + ", ".join(missing)
        )

    admin_pass = _validated_database_secret('VOTING_ADMIN_PASS', admin_pass)
    voter_pass = _validated_database_secret('VOTING_VOTER_PASS', voter_pass)

    parsed = make_url(base_url)
    db_name = os.environ.get('MYSQL_DATABASE') or parsed.database
    if not db_name:
        raise RuntimeError("MYSQL_DATABASE or a database name in DATABASE_URL is required")
    
    return {
        'admin': _build_bind_url(base_url, admin_user, admin_pass, db_name),
        'voters': _build_bind_url(base_url, voter_user, voter_pass, db_name),
    }
