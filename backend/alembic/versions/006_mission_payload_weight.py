"""Add payload_weight_kg to missions table

Revision ID: 006
Revises: 005
Create Date: 2026-06-15 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'missions',
        sa.Column('payload_weight_kg', sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('missions', 'payload_weight_kg')
