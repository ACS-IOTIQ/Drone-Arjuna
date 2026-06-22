"""Expand payload_types with UI-required columns

Revision ID: 007
Revises: 006
Create Date: 2026-06-22 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns — all nullable or with server defaults so existing rows
    # survive without a data migration.
    op.add_column('payload_types', sa.Column('manufacturer',    sa.String(128), nullable=False, server_default=''))
    op.add_column('payload_types', sa.Column('model',           sa.String(128), nullable=False, server_default=''))
    op.add_column('payload_types', sa.Column('category',        sa.String(32),  nullable=False, server_default='sensor'))
    op.add_column('payload_types', sa.Column('weight_kg',       sa.Float(),     nullable=False, server_default='0.0'))
    op.add_column('payload_types', sa.Column('voltage_v',       sa.Float(),     nullable=False, server_default='5.0'))
    op.add_column('payload_types', sa.Column('max_current_a',   sa.Float(),     nullable=False, server_default='2.0'))
    op.add_column('payload_types', sa.Column('has_gimbal',      sa.Boolean(),   nullable=False, server_default='false'))
    op.add_column('payload_types', sa.Column('sensor_type',     sa.String(64),  nullable=True))
    op.add_column('payload_types', sa.Column('resolution',      sa.String(64),  nullable=True))
    op.add_column('payload_types', sa.Column('frame_rate_fps',  sa.Float(),     nullable=True))
    op.add_column('payload_types', sa.Column('payload_function',sa.String(64),  nullable=True))
    op.add_column('payload_types', sa.Column('effective_range_m', sa.Float(),   nullable=True))
    op.add_column('payload_types', sa.Column('notes',           sa.Text(),      nullable=True))
    op.add_column('payload_types', sa.Column('is_active',       sa.Boolean(),   nullable=False, server_default='true'))

    # Remove the old single-field description column
    op.drop_column('payload_types', 'description')


def downgrade() -> None:
    op.add_column('payload_types', sa.Column('description', sa.Text(), nullable=True))

    op.drop_column('payload_types', 'is_active')
    op.drop_column('payload_types', 'notes')
    op.drop_column('payload_types', 'effective_range_m')
    op.drop_column('payload_types', 'payload_function')
    op.drop_column('payload_types', 'frame_rate_fps')
    op.drop_column('payload_types', 'resolution')
    op.drop_column('payload_types', 'sensor_type')
    op.drop_column('payload_types', 'has_gimbal')
    op.drop_column('payload_types', 'max_current_a')
    op.drop_column('payload_types', 'voltage_v')
    op.drop_column('payload_types', 'weight_kg')
    op.drop_column('payload_types', 'category')
    op.drop_column('payload_types', 'model')
    op.drop_column('payload_types', 'manufacturer')
