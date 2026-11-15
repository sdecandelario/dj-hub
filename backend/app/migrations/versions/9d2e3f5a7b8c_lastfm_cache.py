"""lastfm cache

Revision ID: 9d2e3f5a7b8c
Revises: 8c1d2e4f6a7b
Create Date: 2026-11-16 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '9d2e3f5a7b8c'
down_revision = '8c1d2e4f6a7b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('lastfm_cache',
    sa.Column('key', sa.String(), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    with op.batch_alter_table('lastfm_cache', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_lastfm_cache_fetched_at'), ['fetched_at'], unique=False)


def downgrade():
    with op.batch_alter_table('lastfm_cache', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_lastfm_cache_fetched_at'))
    op.drop_table('lastfm_cache')
