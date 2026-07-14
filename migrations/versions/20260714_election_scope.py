"""scope candidates, ballots, receipts, tokens, and signed results to elections

Revision ID: 20260714_election_scope
Revises: 20251005_add_uq_vote_user
Create Date: 2026-07-14 12:00:00.000000
"""

from datetime import datetime, timezone
import secrets

from alembic import op
import sqlalchemy as sa


revision = "20260714_election_scope"
down_revision = "20251005_add_uq_vote_user"
branch_labels = None
depends_on = None


def _constraint_names(inspector, table_name, constraint_type):
    if constraint_type == "unique":
        return {
            item.get("name")
            for item in inspector.get_unique_constraints(table_name)
            if item.get("name")
        }
    return {
        item.get("name")
        for item in inspector.get_foreign_keys(table_name)
        if item.get("name")
    }


def _objects_using_column(inspector, table_name, column_name):
    """Return named schema objects that must be removed with a legacy column."""
    foreign_keys = {
        item.get("name")
        for item in inspector.get_foreign_keys(table_name)
        if column_name in (item.get("constrained_columns") or []) and item.get("name")
    }
    uniques = {
        item.get("name")
        for item in inspector.get_unique_constraints(table_name)
        if column_name in (item.get("column_names") or []) and item.get("name")
    }
    indexes = {
        item.get("name")
        for item in inspector.get_indexes(table_name)
        if column_name in (item.get("column_names") or []) and item.get("name")
    }
    # MySQL reflects a UNIQUE constraint as both a unique constraint and an
    # index with the same name. Drop it exactly once via the constraint API.
    indexes.difference_update(uniques)
    return foreign_keys, uniques, indexes


def _column_map(inspector, table_name):
    return {
        column["name"]: column
        for column in inspector.get_columns(table_name)
    }


def _has_unique(inspector, table_name, columns):
    expected = tuple(columns)
    return any(
        tuple(item.get("column_names") or ()) == expected
        for item in inspector.get_unique_constraints(table_name)
    )


def _has_foreign_key(
    inspector,
    table_name,
    columns,
    referred_table,
    referred_columns,
):
    expected_columns = tuple(columns)
    expected_referred = tuple(referred_columns)
    return any(
        tuple(item.get("constrained_columns") or ()) == expected_columns
        and item.get("referred_table") == referred_table
        and tuple(item.get("referred_columns") or ()) == expected_referred
        for item in inspector.get_foreign_keys(table_name)
    )


def _current_schema_errors(inspector, tables):
    """Return every missing integrity boundary in an apparent current schema."""
    required_columns = {
        "election": {
            "id",
            "blind_signing_key_id",
            "blind_key_recovery_required",
        },
        "candidate": {"id", "election_id"},
        "vote": {"id", "voter_token", "candidate_id", "election_id"},
        "vote_receipt": {"id", "user_id", "election_id"},
        "blind_signature_token": {"id", "user_id", "election_id"},
        "spent_ballot_nullifier": {
            "id",
            "election_id",
            "nullifier_hash",
            "spent_at",
        },
        "result_signing_public_key": {
            "key_id",
            "algorithm",
            "public_key_pem",
            "created_at",
        },
        "signed_election_result": {
            "id",
            "election_id",
            "payload",
            "signature",
            "signer_backend",
            "signature_algorithm",
            "signing_key_id",
            "signing_key_version",
            "signed_at",
            "signed_by",
        },
    }
    errors = []
    for table_name, names in required_columns.items():
        if table_name not in tables:
            errors.append(f"missing table {table_name}")
            continue
        columns = _column_map(inspector, table_name)
        for name in sorted(names - set(columns)):
            errors.append(f"missing column {table_name}.{name}")

    if errors:
        return errors

    non_nullable = {
        "election": {"blind_key_recovery_required"},
        "candidate": {"election_id"},
        "vote": {"voter_token", "candidate_id", "election_id"},
        "vote_receipt": {"user_id", "election_id"},
        "blind_signature_token": {"user_id", "election_id"},
        "spent_ballot_nullifier": {"election_id", "nullifier_hash", "spent_at"},
        "signed_election_result": {
            "election_id",
            "payload",
            "signature",
            "signer_backend",
            "signature_algorithm",
            "signing_key_id",
            "signed_at",
        },
    }
    for table_name, names in non_nullable.items():
        columns = _column_map(inspector, table_name)
        for name in names:
            if columns[name].get("nullable", True):
                errors.append(f"nullable integrity column {table_name}.{name}")

    forbidden_columns = {
        "vote": {"user_id"},
        "blind_signature_token": {
            "ballot_nonce_hash",
            "issued_at",
            "redeemed",
            "redeemed_at",
        },
    }
    for table_name, names in forbidden_columns.items():
        present = set(_column_map(inspector, table_name))
        for name in sorted(names & present):
            errors.append(f"legacy identity-link column {table_name}.{name}")

    unique_requirements = (
        ("candidate", ("id", "election_id")),
        ("vote", ("voter_token",)),
        ("vote_receipt", ("user_id", "election_id")),
        ("blind_signature_token", ("user_id", "election_id")),
        ("spent_ballot_nullifier", ("election_id", "nullifier_hash")),
        ("signed_election_result", ("election_id",)),
    )
    for table_name, columns in unique_requirements:
        if not _has_unique(inspector, table_name, columns):
            errors.append(f"missing unique {table_name}{columns}")

    foreign_key_requirements = (
        ("candidate", ("election_id",), "election", ("id",)),
        (
            "vote",
            ("candidate_id", "election_id"),
            "candidate",
            ("id", "election_id"),
        ),
        ("vote", ("election_id",), "election", ("id",)),
        ("vote_receipt", ("election_id",), "election", ("id",)),
        (
            "blind_signature_token",
            ("election_id",),
            "election",
            ("id",),
        ),
        (
            "spent_ballot_nullifier",
            ("election_id",),
            "election",
            ("id",),
        ),
        ("signed_election_result", ("election_id",), "election", ("id",)),
    )
    for table_name, columns, referred_table, referred_columns in foreign_key_requirements:
        if not _has_foreign_key(
            inspector,
            table_name,
            columns,
            referred_table,
            referred_columns,
        ):
            errors.append(
                f"missing foreign key {table_name}{columns} -> "
                f"{referred_table}{referred_columns}"
            )
    return errors


def upgrade():
    bind = op.get_bind()
    sqlite_mode = bind.dialect.name == "sqlite"
    if sqlite_mode:
        # Alembic batch mode recreates parent tables. Disable enforcement during
        # the copy so existing ON DELETE CASCADE links do not erase child rows.
        bind.execute(sa.text("PRAGMA foreign_keys=OFF"))
    inspector = sa.inspect(bind)

    tables = set(inspector.get_table_names())
    current_markers = {
        "spent_ballot_nullifier",
        "result_signing_public_key",
        "signed_election_result",
    } & tables
    if "election" in tables:
        election_columns = set(_column_map(inspector, "election"))
        current_markers.update(
            election_columns
            & {"blind_signing_key_id", "blind_key_recovery_required"}
        )
    if current_markers:
        errors = _current_schema_errors(inspector, tables)
        if errors:
            if sqlite_mode:
                bind.execute(sa.text("PRAGMA foreign_keys=ON"))
            raise RuntimeError(
                "Refusing to stamp a partial election-integrity schema: "
                + "; ".join(errors)
            )
        if sqlite_mode:
            bind.execute(sa.text("PRAGMA foreign_keys=ON"))
        return

    vote_columns = {item["name"] for item in inspector.get_columns("vote")}
    user_columns = {item["name"] for item in inspector.get_columns("user")}
    legacy_vote_user_id = "user_id" in vote_columns
    legacy_user_has_voted = "has_voted" in user_columns
    if "voter_token" not in vote_columns:
        op.add_column("vote", sa.Column("voter_token", sa.String(64), nullable=True))
        for vote_id in bind.execute(sa.text("SELECT id FROM vote")).scalars():
            bind.execute(
                sa.text("UPDATE vote SET voter_token = :token WHERE id = :vote_id"),
                {"token": secrets.token_hex(32), "vote_id": vote_id},
            )

    op.add_column(
        "election",
        sa.Column("blind_signing_key_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "election",
        sa.Column(
            "blind_key_recovery_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("candidate", sa.Column("election_id", sa.Integer(), nullable=True))
    op.add_column("vote", sa.Column("election_id", sa.Integer(), nullable=True))
    op.add_column("vote_receipt", sa.Column("election_id", sa.Integer(), nullable=True))
    op.add_column(
        "blind_signature_token",
        sa.Column("election_id", sa.Integer(), nullable=True),
    )

    election_id = bind.execute(
        sa.text("SELECT id FROM election ORDER BY created_at ASC, id ASC LIMIT 1")
    ).scalar()
    if election_id is None:
        result = bind.execute(
            sa.text(
                "INSERT INTO election (name, status, created_at) "
                "VALUES (:name, :status, :created_at)"
            ),
            {
                "name": "Imported legacy election",
                "status": "closed",
                "created_at": datetime.now(timezone.utc).replace(tzinfo=None),
            },
        )
        election_id = result.lastrowid

    bind.execute(
        sa.text("UPDATE candidate SET election_id = :election_id"),
        {"election_id": election_id},
    )
    bind.execute(
        sa.text(
            "UPDATE vote SET election_id = "
            "(SELECT candidate.election_id FROM candidate "
            "WHERE candidate.id = vote.candidate_id)"
        )
    )
    bind.execute(
        sa.text("UPDATE vote_receipt SET election_id = :election_id"),
        {"election_id": election_id},
    )
    if legacy_vote_user_id:
        bind.execute(
            sa.text(
                "INSERT INTO vote_receipt (user_id, election_id, voted_at) "
                "SELECT vote.user_id, :election_id, vote.created_at FROM vote "
                "WHERE vote.user_id IS NOT NULL AND NOT EXISTS ("
                "SELECT 1 FROM vote_receipt receipt "
                "WHERE receipt.user_id = vote.user_id)"
            ),
            {"election_id": election_id},
        )
    if legacy_user_has_voted:
        legacy_users = sa.table(
            "user",
            sa.column("id", sa.Integer()),
            sa.column("has_voted", sa.Boolean()),
        )
        voted_user_ids = bind.execute(
            sa.select(legacy_users.c.id).where(
                legacy_users.c.has_voted.is_(True)
            )
        ).scalars()
        for user_id in voted_user_ids:
            bind.execute(
                sa.text(
                    "INSERT INTO vote_receipt (user_id, election_id, voted_at) "
                    "SELECT :user_id, :election_id, :voted_at WHERE NOT EXISTS ("
                    "SELECT 1 FROM vote_receipt WHERE user_id = :user_id)"
                ),
                {
                    "user_id": user_id,
                    "election_id": election_id,
                    "voted_at": datetime.now(timezone.utc).replace(tzinfo=None),
                },
            )

    # Legacy blind authorizations contain a deterministic identity-to-ballot
    # link and cannot be safely converted. Preserve their existence as durable
    # election ambiguity before deleting the linkable rows. An open election
    # with this flag is quarantined and may never receive a newly generated key.
    legacy_authorization_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM blind_signature_token")
    ).scalar_one()
    if legacy_authorization_count:
        bind.execute(
            sa.text(
                "UPDATE election SET blind_key_recovery_required = :required "
                "WHERE status = 'open'"
            ),
            {"required": True},
        )
    bind.execute(sa.text("DELETE FROM blind_signature_token"))

    inspector = sa.inspect(bind)
    receipt_uniques = _constraint_names(inspector, "vote_receipt", "unique")
    token_uniques = _constraint_names(inspector, "blind_signature_token", "unique")
    vote_user_fks, vote_user_uniques, vote_user_indexes = (
        _objects_using_column(inspector, "vote", "user_id")
        if legacy_vote_user_id
        else (set(), set(), set())
    )
    token_columns = {
        item["name"] for item in inspector.get_columns("blind_signature_token")
    }
    token_legacy_fks = set()
    token_legacy_uniques = set()
    token_legacy_indexes = set()
    for column_name in ("ballot_nonce_hash", "issued_at", "redeemed", "redeemed_at"):
        if column_name in token_columns:
            foreign_keys, uniques, indexes = _objects_using_column(
                inspector,
                "blind_signature_token",
                column_name,
            )
            token_legacy_fks.update(foreign_keys)
            token_legacy_uniques.update(uniques)
            token_legacy_indexes.update(indexes)
    with op.batch_alter_table("election") as batch:
        batch.create_check_constraint(
            "ck_election_status",
            "status IN ('draft', 'open', 'closed')",
        )

    with op.batch_alter_table("candidate") as batch:
        batch.alter_column("election_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            "fk_candidate_election",
            "election",
            ["election_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint(
            "uq_candidate_id_election",
            ["id", "election_id"],
        )
        batch.create_index("ix_candidate_election_id", ["election_id"])

    with op.batch_alter_table("vote") as batch:
        for name in sorted(vote_user_indexes):
            batch.drop_index(name)
        for name in sorted(vote_user_uniques):
            batch.drop_constraint(name, type_="unique")
        for name in sorted(vote_user_fks):
            batch.drop_constraint(name, type_="foreignkey")
        if legacy_vote_user_id:
            batch.drop_column("user_id")
        batch.alter_column(
            "voter_token",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch.alter_column("election_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            "fk_vote_candidate_election",
            "candidate",
            ["candidate_id", "election_id"],
            ["id", "election_id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_vote_election",
            "election",
            ["election_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint("uq_vote_voter_token", ["voter_token"])
        batch.create_index("ix_vote_election_id", ["election_id"])

    with op.batch_alter_table("vote_receipt") as batch:
        if "uq_vote_receipt_user" in receipt_uniques:
            batch.drop_constraint("uq_vote_receipt_user", type_="unique")
        batch.alter_column("election_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            "fk_vote_receipt_election",
            "election",
            ["election_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint(
            "uq_vote_receipt_user_election",
            ["user_id", "election_id"],
        )
        batch.create_index("ix_vote_receipt_election_id", ["election_id"])

    if legacy_user_has_voted:
        with op.batch_alter_table("user") as batch:
            batch.drop_column("has_voted")

    with op.batch_alter_table("blind_signature_token") as batch:
        for name in sorted(token_legacy_indexes):
            batch.drop_index(name)
        for name in sorted(token_legacy_uniques - {"uq_blind_sig_token_user"}):
            batch.drop_constraint(name, type_="unique")
        for name in sorted(token_legacy_fks):
            batch.drop_constraint(name, type_="foreignkey")
        if "uq_blind_sig_token_user" in token_uniques:
            batch.drop_constraint("uq_blind_sig_token_user", type_="unique")
        for column_name in ("ballot_nonce_hash", "issued_at", "redeemed", "redeemed_at"):
            if column_name in token_columns:
                batch.drop_column(column_name)
        batch.alter_column("election_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            "fk_blind_signature_token_election",
            "election",
            ["election_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint(
            "uq_blind_sig_token_user_election",
            ["user_id", "election_id"],
        )
        batch.create_index(
            "ix_blind_signature_token_election_id",
            ["election_id"],
        )

    op.create_table(
        "spent_ballot_nullifier",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("election_id", sa.Integer(), nullable=False),
        sa.Column("nullifier_hash", sa.String(length=64), nullable=False),
        sa.Column("spent_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["election_id"],
            ["election.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "election_id",
            "nullifier_hash",
            name="uq_spent_nullifier_election_hash",
        ),
    )
    op.create_index(
        "ix_spent_ballot_nullifier_election_id",
        "spent_ballot_nullifier",
        ["election_id"],
    )

    op.create_table(
        "result_signing_public_key",
        sa.Column("key_id", sa.String(length=64), primary_key=True),
        sa.Column("algorithm", sa.String(length=64), nullable=False),
        sa.Column("public_key_pem", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "signed_election_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("election_id", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("signer_backend", sa.String(length=32), nullable=False),
        sa.Column("signature_algorithm", sa.String(length=64), nullable=False),
        sa.Column("signing_key_id", sa.String(length=255), nullable=False),
        sa.Column("signing_key_version", sa.Integer(), nullable=True),
        sa.Column("signed_at", sa.DateTime(), nullable=False),
        sa.Column("signed_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["election_id"],
            ["election.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signed_by"],
            ["user.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "election_id",
            name="uq_signed_election_result_election",
        ),
    )
    if sqlite_mode:
        bind.execute(sa.text("PRAGMA foreign_keys=ON"))
def downgrade():
    raise RuntimeError(
        "Refusing to downgrade election scoping because it would delete spent "
        "nullifiers, blind authorizations, signed results, and anonymity "
        "boundaries. Roll back application code while retaining this schema."
    )
