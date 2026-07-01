"""Add access_requests table

Revision ID: 008
Revises: 007
Create Date: 2026-06-22 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'access_requests',
        sa.Column('id',             sa.Integer(),              primary_key=True, index=True),
        sa.Column('username',       sa.String(64),             nullable=False),
        sa.Column('full_name',      sa.String(128),            nullable=False),
        sa.Column('email',          sa.String(128),            nullable=False),
        sa.Column('mobile',         sa.String(32),             nullable=True),
        sa.Column('requested_role', sa.String(32),             nullable=False, server_default='viewer'),
        sa.Column('reason',         sa.Text(),                 nullable=True),
        sa.Column('status',         sa.String(16),             nullable=False, server_default='pending'),
        sa.Column('admin_note',     sa.Text(),                 nullable=True),
        sa.Column('temp_password',  sa.String(128),            nullable=True),
        sa.Column('created_at',     sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('reviewed_at',    sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('access_requests')
