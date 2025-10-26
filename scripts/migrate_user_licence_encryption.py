"""
Backfill script to migrate User.driver_lic_no to encrypted storage and populate
User.driver_lic_hash (deterministic SHA-256) for uniqueness and lookups.

- Adds driver_lic_hash column if missing
- Creates a unique index on driver_lic_hash if missing
- Re-encrypts existing plaintext driver_lic_no by reassigning the same value
  (triggers SQLAlchemy EncryptedType process_bind_param)
- Backfills driver_lic_hash for every user

Run with the app environment configured (DATABASE_URL, VOTER_PII_KEY_BASE64, etc.).
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from sqlalchemy import text

# Ensure app package is importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app, db
from app.models import User, _hash_lic
from app.security.encryption import ChaChaEncryptionService


def column_exists(engine, table: str, column: str) -> bool:
    insp = db.inspect(engine)
    cols = [c.get('name') or c['name'] for c in insp.get_columns(table)]
    return column in cols


def index_exists(engine, table: str, index_name: str) -> bool:
    insp = db.inspect(engine)
    try:
        idx = insp.get_indexes(table)
    except Exception:
        return False
    return any(i.get('name') == index_name for i in idx)


def add_column_if_missing(engine, table: str, ddl: str, column: str):
    if not column_exists(engine, table, column):
        with engine.begin() as conn:
            conn.execute(text(ddl))
        print(f"Added column {table}.{column}")
    else:
        print(f"Column {table}.{column} already exists")


def add_unique_index_if_missing(engine, table: str, column: str, index_name: str):
    if not index_exists(engine, table, index_name):
        dialect = engine.dialect.name
        if dialect == 'sqlite':
            ddl = f"CREATE UNIQUE INDEX {index_name} ON {table}({column});"
        else:
            # MySQL / Postgres
            ddl = f"CREATE UNIQUE INDEX {index_name} ON {table}({column});"
        with engine.begin() as conn:
            conn.execute(text(ddl))
        print(f"Created unique index {index_name} on {table}({column})")
    else:
        print(f"Unique index {index_name} already exists")


def migrate():
    app = create_app()
    with app.app_context():
        engine = db.engine

        # Ensure the new column exists
        # For wide compatibility, use VARCHARS
        if engine.dialect.name == 'sqlite':
            add_column_if_missing(engine, 'user', "ALTER TABLE user ADD COLUMN driver_lic_hash VARCHAR(64);", 'driver_lic_hash')
        else:
            add_column_if_missing(engine, 'user', "ALTER TABLE user ADD COLUMN driver_lic_hash VARCHAR(64) NULL;", 'driver_lic_hash')

        # Ensure the licence column can hold ciphertext (Base64 ~ up to ~255)
        if engine.dialect.name != 'sqlite':
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE user MODIFY driver_lic_no VARCHAR(255) NOT NULL;"))
            print("Altered column user.driver_lic_no to VARCHAR(255)")

        # Add unique index on the hash
        add_unique_index_if_missing(engine, 'user', 'driver_lic_hash', 'uq_user_driver_lic_hash')

        print("Backfilling driver_lic_hash and re-encrypting driver_lic_no...")
        # Initialize encryption service (uses VOTER_PII_KEY_BASE64)
        ChaChaEncryptionService.initialize(os.environ.get('VOTER_PII_KEY_BASE64'))
        service = ChaChaEncryptionService.get_instance()
        count = 0
        q = User.query
        for user in q.yield_per(200):
            try:
                plain = getattr(user, 'driver_lic_no', None)
                # Backfill hash
                h = _hash_lic(plain)
                user.driver_lic_hash = h
                # If value looks like legacy plaintext (short), encrypt via direct SQL update
                if plain and len(str(plain)) < 40:
                    encrypted = service.encrypt(str(plain))
                    # Direct SQL to avoid double-encryption via TypeDecorator
                    db.session.execute(text("UPDATE `user` SET driver_lic_no = :enc WHERE id = :id"), {"enc": encrypted, "id": user.id})
                count += 1
                if count % 200 == 0:
                    db.session.commit()
                    print(f"Committed {count} users...")
            except Exception as e:
                db.session.rollback()
                print(f"Error processing user id={getattr(user, 'id', '?')}: {e}")
        db.session.commit()
        print(f"Done. Processed {count} users.")


if __name__ == '__main__':
    migrate()
