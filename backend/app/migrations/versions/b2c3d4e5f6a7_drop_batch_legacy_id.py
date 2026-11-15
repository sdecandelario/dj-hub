"""drop batch legacy_id

The batches imported from the old dj-library script stay in the history as ordinary file changes.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-16 13:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE batches SET kind = 'apply' WHERE kind = 'legacy'")
    with op.batch_alter_table('batches', schema=None) as batch_op:
        batch_op.drop_column('legacy_id')


def downgrade():
    with op.batch_alter_table('batches', schema=None) as batch_op:
        batch_op.add_column(sa.Column('legacy_id', sa.String(), nullable=True))
