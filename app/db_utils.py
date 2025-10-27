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