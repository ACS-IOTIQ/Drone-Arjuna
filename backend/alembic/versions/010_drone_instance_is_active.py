"""Add is_active to drone_instances for soft-delete/removal

Revision ID: 010
Revises: 009
Create Date: 2026-07-06 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('drone_instances', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'))


def downgrade() -> None:
    op.drop_column('drone_instances', 'is_active')
