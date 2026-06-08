"""Initial schema — users, drone_types, drone_instances, missions, waypoints

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('users',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('username', sa.String(64), unique=True, index=True, nullable=False),
        sa.Column('email', sa.String(128), unique=True, index=True, nullable=False),
        sa.Column('hashed_password', sa.String(128), nullable=False),
        sa.Column('full_name', sa.String(128), server_default=''),
        sa.Column('role', sa.String(32), server_default='viewer'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table('drone_types',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('name', sa.String(128), unique=True, nullable=False),
        sa.Column('manufacturer', sa.String(128), nullable=False),
        sa.Column('model', sa.String(128), nullable=False),
        sa.Column('size_class', sa.String(32), nullable=False),
        sa.Column('mission_type', sa.String(64), nullable=False),
        sa.Column('is_vtol', sa.Boolean(), server_default='true'),
        sa.Column('max_speed_ms', sa.Float(), nullable=False),
        sa.Column('cruise_speed_ms', sa.Float(), nullable=False),
        sa.Column('max_altitude_m', sa.Float(), nullable=False),
        sa.Column('endurance_h', sa.Float(), nullable=False),
        sa.Column('range_km', sa.Float(), nullable=False),
        sa.Column('max_takeoff_weight_kg', sa.Float(), nullable=False),
        sa.Column('max_payload_weight_kg', sa.Float(), nullable=False),
        sa.Column('autopilot_type', sa.String(64), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table('drone_instances',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('call_sign', sa.String(64), unique=True, index=True, nullable=False),
        sa.Column('drone_type_id', sa.Integer(), nullable=False),
        sa.Column('serial_number', sa.String(128), unique=True, nullable=False),
        sa.Column('mavlink_system_id', sa.Integer(), server_default='1'),
        sa.Column('status', sa.String(32), server_default='offline'),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=True),
        sa.Column('total_flight_hours', sa.Float(), server_default='0.0'),
        sa.Column('notes', sa.Text(), nullable=True),
    )

    op.create_table('missions',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('mission_type', sa.String(64), server_default='ISR'),
        sa.Column('status', sa.String(32), server_default='planning'),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('drone_instance_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('geofence', sa.JSON(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
    )

    op.create_table('waypoints',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('mission_id', sa.Integer(), index=True, nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('altitude_m', sa.Float(), nullable=False),
        sa.Column('altitude_ref', sa.String(8), server_default='AGL'),
        sa.Column('speed_ms', sa.Float(), nullable=True),
        sa.Column('heading_deg', sa.Float(), nullable=True),
        sa.Column('action', sa.String(32), server_default='none'),
        sa.Column('loiter_time_s', sa.Float(), nullable=True),
        sa.Column('is_home', sa.Boolean(), server_default='false'),
    )


def downgrade() -> None:
    op.drop_table('waypoints')
    op.drop_table('missions')
    op.drop_table('drone_instances')
    op.drop_table('drone_types')
    op.drop_table('users')