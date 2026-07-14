"""persist OTP attempts server-side

Revision ID: 20260714_server_side_otp
Revises: 20260714_election_scope
Create Date: 2026-07-14 18:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_server_side_otp"
down_revision = "20260714_election_scope"
branch_labels = None
depends_on = None


def upgrade():
    if "otp_challenge" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "otp_challenge",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "failed_attempts >= 0 AND failed_attempts <= 5",
            name="ck_otp_challenge_failed_attempts",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "purpose",
            name="uq_otp_challenge_user_purpose",
        ),
    )
    op.create_index(
        "ix_otp_challenge_user_id",
        "otp_challenge",
        ["user_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_otp_challenge_user_id", table_name="otp_challenge")
    op.drop_table("otp_challenge")
