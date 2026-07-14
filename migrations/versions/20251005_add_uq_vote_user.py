"""add unique constraint to vote.user_id

Revision ID: 20251005_add_uq_vote_user
Revises: 
Create Date: 2025-10-05 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20251005_add_uq_vote_user'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'vote' not in inspector.get_table_names():
        # This repository began using Alembic after the original schema was
        # created with SQLAlchemy. A genuinely empty database should start at
        # the current model schema; later revisions detect that state and no-op.
        from app import db
        from app import models as _models  # noqa: F401  # agent-quality: allow: registers migration metadata

        db.metadata.create_all(bind=bind)
        return

    vote_columns = {column['name'] for column in inspector.get_columns('vote')}
    if 'user_id' not in vote_columns:
        return
    has_unique_user = any(
        constraint.get('column_names') == ['user_id']
        for constraint in inspector.get_unique_constraints('vote')
    )
    if not has_unique_user:
        with op.batch_alter_table('vote') as batch:
            batch.create_unique_constraint('uq_vote_user', ['user_id'])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'vote' not in inspector.get_table_names():
        return
    constraint_names = {
        constraint.get('name')
        for constraint in inspector.get_unique_constraints('vote')
    }
    if 'uq_vote_user' in constraint_names:
        with op.batch_alter_table('vote') as batch:
            batch.drop_constraint('uq_vote_user', type_='unique')
