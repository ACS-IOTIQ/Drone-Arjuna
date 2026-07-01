"""Drop payloads table

Revision ID: 009
Revises: 008
Create Date: 2026-06-22 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table('payloads')


def downgrade() -> None:
    op.create_table(
        'payloads',
        sa.Column('id',              sa.Integer(),   primary_key=True, index=True),
        sa.Column('name',            sa.String(128), nullable=False),
        sa.Column('payload_type_id', sa.Integer(),
                  sa.ForeignKey('payload_types.id'), nullable=False, index=True),
        sa.Column('drone_id',        sa.Integer(),
                  sa.ForeignKey('drone_instances.id'), nullable=True, index=True),
        sa.Column('weight',          sa.Float(),     nullable=False),
        sa.Column('status',          sa.String(32),  server_default='available'),
        sa.Column('manufacturer',    sa.String(128), nullable=False),
        sa.Column('serial_number',   sa.String(128), unique=True, nullable=False),
        sa.Column('created_at',      sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
