"""add_threat_system

Revision ID: 49341d048fb9
Revises: 009
Create Date: 2026-06-29 06:10:40.385671

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '49341d048fb9'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'threat_systems',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('category', sa.String(length=16), nullable=False),
        sa.Column('manufacturer', sa.String(length=128), nullable=False),
        sa.Column('country', sa.String(length=64), nullable=False),
        sa.Column('max_range_km', sa.Float(), nullable=True),
        sa.Column('max_altitude_m', sa.Float(), nullable=True),
        sa.Column('max_speed_kmh', sa.Float(), nullable=True),
        sa.Column('radar_cross_section_m2', sa.Float(), nullable=True),
        sa.Column('countermeasures', sa.JSON(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('classification', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_threat_systems_id'), 'threat_systems', ['id'], unique=False)
    op.create_index(op.f('ix_threat_systems_name'), 'threat_systems', ['name'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_threat_systems_name'), table_name='threat_systems')
    op.drop_index(op.f('ix_threat_systems_id'), table_name='threat_systems')
    op.drop_table('threat_systems')
