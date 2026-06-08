"""Add audit_log table

Revision ID: 003
Revises: 002
Create Date: 2026-06-08 15:04:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'audit_log',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('category', sa.String(32), nullable=False),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('drone_id', sa.Integer(), nullable=True),
        sa.Column('mission_id', sa.Integer(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('detail', postgresql.JSONB(), nullable=True),
        sa.Column('severity', sa.String(16), server_default='INFO', nullable=False),
    )
    op.create_index('ix_audit_log_timestamp', 'audit_log', ['timestamp'])
    op.create_index('ix_audit_log_user', 'audit_log', ['user_id'])
    op.create_index('ix_audit_log_category', 'audit_log', ['category', 'timestamp'])


def downgrade() -> None:
    op.drop_index('ix_audit_log_category', table_name='audit_log')
    op.drop_index('ix_audit_log_user', table_name='audit_log')
    op.drop_index('ix_audit_log_timestamp', table_name='audit_log')
    op.drop_table('audit_log')
