"""Explicitly migrate reviewed legacy PII into the v1 AEAD envelope.

There is intentionally no auto-detection mode. Operators must state whether
all non-current values in the selected database are old unversioned ChaCha20-
Poly1305 ciphertext, old Fernet ciphertext under the supplied key, or
explicitly marked legacy plaintext. The transaction rolls back if any selected
value does not match that contract.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, inspect, text


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app, db  # noqa: E402; agent-quality: allow: import follows script root bootstrap
from app.models import (  # noqa: E402; agent-quality: allow: import follows script root bootstrap
    ENCRYPTED_LICENCE_COLUMN_LENGTH,
    ENCRYPTED_LONG_PII_COLUMN_LENGTH,
    ENCRYPTED_SHORT_PII_COLUMN_LENGTH,
    _hash_lic,
)
from app.security.encryption import ChaChaEncryptionService  # noqa: E402; agent-quality: allow: import follows script root bootstrap


FIELDS = {
    "user": ("driver_lic_no",),
    "electoral_roll": (
        "driver_license_number",
        "full_name",
        "address_line1",
        "address_line2",
        "suburb",
        "state",
        "postcode",
    ),
}
LICENCE_HASH_COLUMNS = {
    ("user", "driver_lic_no"): "driver_lic_hash",
    ("electoral_roll", "driver_license_number"): "driver_license_hash",
}
MIN_ENCRYPTED_COLUMN_LENGTHS = {
    ("user", "driver_lic_no"): ENCRYPTED_LICENCE_COLUMN_LENGTH,
    ("electoral_roll", "driver_license_number"): ENCRYPTED_LICENCE_COLUMN_LENGTH,
    ("electoral_roll", "full_name"): ENCRYPTED_LONG_PII_COLUMN_LENGTH,
    ("electoral_roll", "address_line1"): ENCRYPTED_LONG_PII_COLUMN_LENGTH,
    ("electoral_roll", "address_line2"): ENCRYPTED_LONG_PII_COLUMN_LENGTH,
    ("electoral_roll", "suburb"): ENCRYPTED_LONG_PII_COLUMN_LENGTH,
    ("electoral_roll", "state"): ENCRYPTED_SHORT_PII_COLUMN_LENGTH,
    ("electoral_roll", "postcode"): ENCRYPTED_SHORT_PII_COLUMN_LENGTH,
}


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=("legacy-chacha", "legacy-fernet", "marked-plaintext"),
        required=True,
        help=(
            "Explicit format of every non-current value. Plaintext must first "
            "be reviewed and prefixed with svpii:legacy-plaintext:v0:."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the migration. Without this flag, validate only.",
    )
    return parser.parse_args()


def _legacy_fernet(source: str) -> Fernet | None:
    if source != "legacy-fernet":
        return None
    key = os.environ.get("OLD_FERNET_KEY")
    if not key:
        raise RuntimeError("OLD_FERNET_KEY is required for legacy-fernet migration")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("OLD_FERNET_KEY is not a valid Fernet key") from exc


def _convert(service, value, source, fernet=None):
    if value.startswith(service.ENVELOPE_PREFIX):
        # Authenticate current values too. A corrupted current envelope must
        # abort the migration rather than being silently skipped.
        service.decrypt(value)
        return value, False
    if source == "legacy-chacha":
        return service.migrate_legacy_ciphertext(value), True
    if source == "legacy-fernet":
        if fernet is None:
            raise RuntimeError("A validated Fernet key is required")
        try:
            plaintext = fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
            raise RuntimeError("Legacy Fernet ciphertext failed decryption") from exc
        return service.encrypt(plaintext), True
    return service.migrate_legacy_plaintext(value), True


def _validate_encrypted_column_capacity(engine, table_names):
    """Return reflected capacities after validating the schema minimums."""
    inspector = inspect(engine)
    failures = []
    columns_by_table = {}
    for table, _field in MIN_ENCRYPTED_COLUMN_LENGTHS:
        if table not in table_names or table in columns_by_table:
            continue
        columns_by_table[table] = {
            column["name"]: column
            for column in inspector.get_columns(table)
        }

    for (table, field), required_length in MIN_ENCRYPTED_COLUMN_LENGTHS.items():
        column = columns_by_table.get(table, {}).get(field)
        if column is None:
            continue
        column_type = column["type"]
        if not isinstance(column_type, String):
            failures.append(
                f"{table}.{field} is {column_type}, expected a text column"
            )
            continue
        reflected_length = getattr(column_type, "length", None)
        # TEXT-like columns report no finite length and are sufficiently wide.
        if reflected_length is not None and reflected_length < required_length:
            failures.append(
                f"{table}.{field} has capacity {reflected_length}, "
                f"requires at least {required_length}"
            )

    if failures:
        details = "; ".join(failures)
        raise RuntimeError(
            "PII migration refused before writes because encrypted columns are "
            f"too small: {details}. Run `python -m flask db upgrade` first."
        )
    return {
        (table, field): getattr(column["type"], "length", None)
        for table, fields in FIELDS.items()
        for field in fields
        if (column := columns_by_table.get(table, {}).get(field)) is not None
    }


def migrate(source: str, apply_changes: bool) -> int:
    app = create_app()
    with app.app_context():
        service = ChaChaEncryptionService.get_instance()
        engine = db.engine
        table_names = set(inspect(engine).get_table_names())
        field_capacities = _validate_encrypted_column_capacity(engine, table_names)
        fernet = _legacy_fernet(source)
        converted = 0

        with engine.begin() as connection:
            for table, expected_fields in FIELDS.items():
                if table not in table_names:
                    continue
                columns = {
                    column["name"] for column in inspect(connection).get_columns(table)
                }
                fields = [field for field in expected_fields if field in columns]
                if not fields:
                    continue

                quoted_table = f"`{table}`"
                selected = ", ".join(["id", *[f"`{field}`" for field in fields]])
                rows = connection.execute(
                    # Table and column identifiers come only from the fixed
                    # FIELDS allowlist and reflected schema names.
                    text(f"SELECT {selected} FROM {quoted_table}")  # noqa: S608; agent-quality: allow: identifiers are allowlisted
                ).mappings()
                for row in rows:
                    updates = {}
                    for field in fields:
                        value = row[field]
                        if value is None:
                            continue
                        try:
                            migrated, changed = _convert(
                                service,
                                value,
                                source,
                                fernet,
                            )
                            capacity = field_capacities.get((table, field))
                            if capacity is not None and len(migrated) > capacity:
                                raise RuntimeError(
                                    f"generated envelope length {len(migrated)} "
                                    f"exceeds reflected capacity {capacity}"
                                )
                        except Exception as exc:
                            raise RuntimeError(
                                f"PII migration rejected {table}.{field} at row "
                                f"id={row['id']}; no changes were committed"
                            ) from exc
                        if not changed:
                            continue
                        updates[field] = migrated
                        converted += 1
                        hash_column = LICENCE_HASH_COLUMNS.get((table, field))
                        if hash_column and hash_column in columns:
                            updates[hash_column] = _hash_lic(service.decrypt(migrated))

                    if updates and apply_changes:
                        assignments = ", ".join(
                            f"`{field}` = :{field}" for field in updates
                        )
                        connection.execute(
                            text(
                                f"UPDATE {quoted_table} SET {assignments} "  # noqa: S608; agent-quality: allow: identifiers are allowlisted
                                "WHERE id = :row_id"
                            ),
                            {**updates, "row_id": row["id"]},
                        )

        mode = "migrated" if apply_changes else "validated"
        print(f"PII envelope migration {mode} {converted} legacy field values.")
        return converted


if __name__ == "__main__":
    arguments = _parse_args()
    migrate(arguments.source, arguments.apply)
