from __future__ import with_statement
import sys
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Alembic Config, provides access to values in the .ini file.
config = context.config

# Setup logging from Alembic config file
fileConfig(config.config_file_name, disable_existing_loggers=False)

# Ensure project root is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import Flask app and models metadata
from app import create_app, db

target_metadata = db.metadata


def run_migrations_offline():
    """
    Run migrations in 'offline' mode for the default database only.
    For multi-bind migrations, prefer online mode or invoke per-bind offline runs.
    """
    # Fall back to a generic URL (may be None) - offline is rarely used in this project
    # Use an absolute path for the fallback SQLite database to avoid directory issues.
    fallback_db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app.db'))
    url = config.get_main_option("sqlalchemy.url") or f"sqlite:///{fallback_db_path}"
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run each schema migration once against the shared election database.

    The admin and voters binds use different credentials for the same schema.
    Replaying DDL once per credential would attempt to add every column three
    times and could leave separate Alembic version tables out of sync.
    """
    app = create_app()
    with app.app_context():
        with db.engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                version_table="alembic_version",
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
