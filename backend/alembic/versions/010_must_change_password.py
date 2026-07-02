"""Add must_change_password to users

Revision ID: 010
Revises: 009
Create Date: 2026-07-02 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '010'
down_revision = ('009', '49341d048fb9')
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('users', 'must_change_password')
