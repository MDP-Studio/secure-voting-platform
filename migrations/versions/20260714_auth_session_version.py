"""Add durable authentication session version.

Revision ID: 20260714_auth_session_version
Revises: 20260714_server_side_otp
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_auth_session_version"
down_revision = "20260714_server_side_otp"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("user")}
    if "session_version" not in columns:
        with op.batch_alter_table("user") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "session_version",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )


def downgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("user")}
    if "session_version" in columns:
        with op.batch_alter_table("user") as batch_op:
            batch_op.drop_column("session_version")
