"""Add drone_config_templates table

Revision ID: 005
Revises: 004
Create Date: 2026-06-15 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'drone_config_templates',
        sa.Column('id',            sa.Integer(),              primary_key=True, index=True),
        sa.Column('name',          sa.String(128), unique=True, nullable=False),
        sa.Column('description',   sa.Text(),                 nullable=True),
        sa.Column('drone_type_id', sa.Integer(),
                  sa.ForeignKey('drone_types.id'), nullable=False, index=True),
        sa.Column('settings',      sa.JSON(),                 nullable=False,
                  server_default='{}'),
        sa.Column('is_active',     sa.Boolean(),              nullable=False,
                  server_default=sa.text('true')),
        sa.Column('created_at',    sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column('updated_at',    sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('drone_config_templates')
