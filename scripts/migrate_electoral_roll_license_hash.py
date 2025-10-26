"""
Backfill driver_license_hash for ElectoralRoll and add unique index.

- Adds column electoral_roll.driver_license_hash if missing
- Creates a unique index on driver_license_hash if missing
- Backfills the hash based on decrypted driver_license_number via ORM

Run with proper environment (DATABASE_URL, VOTER_PII_KEY_BASE64, etc.).
"""
from __future__ import annotations
import sys
import os
from pathlib import Path
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app, db
from app.models import ElectoralRoll, _hash_lic
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

        # Add column
        add_column_if_missing(engine, 'electoral_roll', "ALTER TABLE electoral_roll ADD COLUMN driver_license_hash VARCHAR(64);", 'driver_license_hash')

        # Add unique index
        add_unique_index_if_missing(engine, 'electoral_roll', 'driver_license_hash', 'uq_roll_driver_license_hash')

        # Backfill via ORM so EncryptedType transparently decrypts
        print("Backfilling electoral_roll.driver_license_hash and encrypting legacy plaintext values...")
        # Initialize encryption service
        ChaChaEncryptionService.initialize(os.environ.get('VOTER_PII_KEY_BASE64'))
        service = ChaChaEncryptionService.get_instance()
        count = 0
        for row in ElectoralRoll.query.yield_per(200):
            try:
                # Accessing row.driver_license_number returns decrypted value
                plain = row.driver_license_number
                row.driver_license_hash = _hash_lic(plain)
                # If value looks like legacy plaintext (short), encrypt via direct SQL update
                if plain and len(str(plain)) < 40:
                    encrypted = service.encrypt(str(plain))
                    db.session.execute(text("UPDATE electoral_roll SET driver_license_number = :enc WHERE id = :id"), {"enc": encrypted, "id": row.id})
                count += 1
                if count % 200 == 0:
                    db.session.commit()
                    print(f"Committed {count} rows...")
            except Exception as e:
                db.session.rollback()
                print(f"Error processing roll id={getattr(row, 'id', '?')}: {e}")
        db.session.commit()
        print(f"Done. Processed {count} rows.")


if __name__ == '__main__':
    migrate()
