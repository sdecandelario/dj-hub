"""drop job legacy_id

Revision ID: a1b2c3d4e5f6
Revises: 9d2e3f5a7b8c
Create Date: 2026-11-16 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '9d2e3f5a7b8c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_column('legacy_id')


def downgrade():
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('legacy_id', sa.String(), nullable=True))
