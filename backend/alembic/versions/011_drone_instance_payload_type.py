"""add payload_type_id to drone_instances

Revision ID: 011
Revises: 010, 010_must_change_password, 49341d048fb9
Create Date: 2026-07-11

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '011'
down_revision: Union[str, Sequence[str], None] = (
    '010',
    '010_must_change_password',
    '49341d048fb9',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'drone_instances',
        sa.Column('payload_type_id', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('drone_instances', 'payload_type_id')
