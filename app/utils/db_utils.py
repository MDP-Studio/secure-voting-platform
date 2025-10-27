# db_utils.py
import os
import time
from sqlalchemy import create_engine, text


def wait_for_db(max_attempts=30, delay=2):
    """Wait for the database to be ready with timeout."""
    db_url = os.environ.get('DATABASE_URL') or ('sqlite:///' + os.path.join(os.path.dirname(__file__), '..', 'instance', 'app.db'))
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
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(base_url)
    netloc_parts = parsed.netloc.split('@')
    if len(netloc_parts) == 2:
        host_port = netloc_parts[1]
        netloc = f"{user}:{password}@{host_port}"
    else:
        # No auth in original, assume host:port
        netloc = f"{user}:{password}@{parsed.netloc}"
    path = f"/{db_name}"
    return urlunparse((parsed.scheme, netloc, path, parsed.params, parsed.query, parsed.fragment))


def _build_db_binds(instance_path):
    """Build database bind URLs dynamically from DATABASE_URL and credentials."""
    base_url = os.environ.get('DATABASE_URL') or ('sqlite:///' + os.path.join(instance_path, 'app.db'))
    
    # For SQLite, binds don't apply (single file), so use the same URL
    if base_url.startswith('sqlite'):
        return {
            'admin': base_url,
            'voters': base_url,
        }
    
    # For other DBs, build URLs with different credentials and DB names
    admin_user = os.environ.get('VOTING_ADMIN_USER', 'voting_admin')
    admin_pass = os.environ.get('VOTING_ADMIN_PASS', 'adminpass')
    voter_user = os.environ.get('VOTING_VOTER_USER', 'voting_voter')
    voter_pass = os.environ.get('VOTING_VOTER_PASS', 'voterpass')
    
    return {
        'admin': _build_bind_url(base_url, admin_user, admin_pass, 'votingdb'),
        'voters': _build_bind_url(base_url, voter_user, voter_pass, 'votingdb'),
    }