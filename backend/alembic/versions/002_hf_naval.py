"""HF link support — naval_vessels table, drone home_vessel_id, mission home_point_type

Revision ID: 002
Revises: 001
Create Date: 2026-05-25 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    from alembic import op as _op

    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    # naval_vessels — create only if it doesn't already exist
    if 'naval_vessels' not in existing_tables:
        op.create_table('naval_vessels',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('vessel_id', sa.String(32), unique=True, index=True, nullable=False),
            sa.Column('name', sa.String(128), nullable=False),
            sa.Column('vessel_type', sa.String(64), nullable=False),
            sa.Column('hull_number', sa.String(32), nullable=True),
            sa.Column('latitude', sa.Float(), nullable=True),
            sa.Column('longitude', sa.Float(), nullable=True),
            sa.Column('heading_deg', sa.Float(), nullable=True),
            sa.Column('speed_kts', sa.Float(), nullable=True),
            sa.Column('position_updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('sea_state', sa.Integer(), server_default='0'),
            sa.Column('deck_status', sa.String(32), server_default='clear'),
            sa.Column('landing_spots', sa.Integer(), server_default='1'),
            sa.Column('hf_modem_type', sa.String(64), nullable=True),
            sa.Column('hf_frequency_mhz', sa.Float(), nullable=True),
            sa.Column('hf_link_encrypted', sa.Boolean(), server_default='true'),
            sa.Column('is_active', sa.Boolean(), server_default='true'),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    # Drone instances — add home_vessel_id only if missing
    di_cols = {c['name'] for c in inspector.get_columns('drone_instances')}
    if 'home_vessel_id' not in di_cols:
        op.add_column(
            'drone_instances',
            sa.Column('home_vessel_id', sa.Integer(), nullable=True)
        )

    # Missions — add home_point_type and home_vessel_id only if missing
    m_cols = {c['name'] for c in inspector.get_columns('missions')}
    if 'home_point_type' not in m_cols:
        op.add_column(
            'missions',
            sa.Column('home_point_type', sa.String(32), server_default='fixed')
        )
    if 'home_vessel_id' not in m_cols:
        op.add_column(
            'missions',
            sa.Column('home_vessel_id', sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    op.drop_column('missions', 'home_vessel_id')
    op.drop_column('missions', 'home_point_type')
    op.drop_column('drone_instances', 'home_vessel_id')
    op.drop_table('naval_vessels')
