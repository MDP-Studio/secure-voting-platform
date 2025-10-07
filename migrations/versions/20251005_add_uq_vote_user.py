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
    # create unique constraint on vote.user_id
    op.create_unique_constraint('uq_vote_user', 'vote', ['user_id'])


def downgrade():
    op.drop_constraint('uq_vote_user', 'vote', type_='unique')
