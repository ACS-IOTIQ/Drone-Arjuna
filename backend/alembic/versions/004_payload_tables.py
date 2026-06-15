"""Add payload_types and payloads tables

Revision ID: 004
Revises: 003
Create Date: 2026-06-12 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── payload_types ─────────────────────────────────────────────────
    op.create_table(
        'payload_types',
        sa.Column('id',          sa.Integer(),             primary_key=True, index=True),
        sa.Column('name',        sa.String(128), unique=True, nullable=False),
        sa.Column('description', sa.Text(),                nullable=True),
        sa.Column('created_at',  sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── payloads ──────────────────────────────────────────────────────
    op.create_table(
        'payloads',
        sa.Column('id',              sa.Integer(),  primary_key=True, index=True),
        sa.Column('name',            sa.String(128), nullable=False),
        sa.Column('payload_type_id', sa.Integer(),
                  sa.ForeignKey('payload_types.id'), nullable=False, index=True),
        sa.Column('drone_id',        sa.Integer(),
                  sa.ForeignKey('drone_instances.id'), nullable=True, index=True),
        sa.Column('weight',          sa.Float(),    nullable=False),
        sa.Column('status',          sa.String(32), server_default='available'),
        sa.Column('manufacturer',    sa.String(128), nullable=False),
        sa.Column('serial_number',   sa.String(128), unique=True, nullable=False),
        sa.Column('created_at',      sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('payloads')
    op.drop_table('payload_types')
