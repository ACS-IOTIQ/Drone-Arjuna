"""Persist mission-wide altitude and speed settings.

Revision ID: 018
Revises: 017, 49341d048fb9
Create Date: 2026-10-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "018"
down_revision: Union[str, Sequence[str], None] = ("017", "49341d048fb9")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("missions", sa.Column("altitude_m", sa.Float(), nullable=True))
    op.add_column("missions", sa.Column("speed_ms", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("missions", "speed_ms")
    op.drop_column("missions", "altitude_m")
