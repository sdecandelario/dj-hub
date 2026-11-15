"""job pid

Revision ID: 8c1d2e4f6a7b
Revises: 57a95dd0f9fd
Create Date: 2026-11-15 20:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '8c1d2e4f6a7b'
down_revision = '57a95dd0f9fd'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pid', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_column('pid')
