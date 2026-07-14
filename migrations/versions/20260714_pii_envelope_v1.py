"""Widen encrypted PII columns for the versioned AEAD envelope.

Revision ID: 20260714_pii_envelope_v1
Revises: 20260714_auth_session_version
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_pii_envelope_v1"
down_revision = "20260714_auth_session_version"
branch_labels = None
depends_on = None


_TARGET_LENGTHS = {
    "user": {
        "driver_lic_no": 255,
    },
    "electoral_roll": {
        "driver_license_number": 255,
        "full_name": 1536,
        "address_line1": 1536,
        "address_line2": 1536,
        "suburb": 1536,
        "state": 512,
        "postcode": 512,
    },
}


def _widen_columns(inspector, table_name):
    columns = {
        column["name"]: column
        for column in inspector.get_columns(table_name)
    }
    changes = []
    for name, target_length in _TARGET_LENGTHS[table_name].items():
        column = columns.get(name)
        if column is None:
            continue
        existing_type = column["type"]
        existing_length = getattr(existing_type, "length", None)
        if existing_length is None or existing_length >= target_length:
            continue
        changes.append(
            (name, existing_type, column.get("nullable", True), target_length)
        )
    return columns, changes


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    for table_name in _TARGET_LENGTHS:
        if table_name not in table_names:
            continue
        _columns, changes = _widen_columns(inspector, table_name)
        if not changes:
            continue
        with op.batch_alter_table(table_name) as batch_op:
            for name, existing_type, nullable, target_length in changes:
                batch_op.alter_column(
                    name,
                    existing_type=existing_type,
                    type_=sa.String(length=target_length),
                    existing_nullable=nullable,
                )

    if "electoral_roll" not in table_names:
        return

    inspector = sa.inspect(bind)
    columns = {
        column["name"]: column
        for column in inspector.get_columns("electoral_roll")
    }

    ciphertext_unique_constraints = [
        constraint["name"]
        for constraint in inspector.get_unique_constraints("electoral_roll")
        if constraint.get("name")
        and constraint.get("column_names") == ["driver_license_number"]
    ]

    if ciphertext_unique_constraints:
        with op.batch_alter_table("electoral_roll") as batch_op:
            for constraint_name in ciphertext_unique_constraints:
                batch_op.drop_constraint(constraint_name, type_="unique")

    # SQLite batch table recreation can discard an unnamed inline UNIQUE
    # declaration. The keyed blind index, unlike randomized ciphertext, is the
    # authoritative uniqueness boundary and must remain enforced.
    refreshed = sa.inspect(bind)
    hash_is_unique = any(
        constraint.get("column_names") == ["driver_license_hash"]
        for constraint in refreshed.get_unique_constraints("electoral_roll")
    )
    if "driver_license_hash" in columns and not hash_is_unique:
        with op.batch_alter_table("electoral_roll") as batch_op:
            batch_op.create_unique_constraint(
                "uq_electoral_roll_driver_license_hash",
                ["driver_license_hash"],
            )


def downgrade():
    # Narrowing these columns can truncate authenticated ciphertext and destroy
    # PII. The safe rollback is an application rollback while retaining width.
    raise RuntimeError(
        "Refusing to narrow encrypted PII columns because doing so can truncate "
        "authenticated ciphertext. Roll back the application while retaining "
        "the widened database schema."
    )
