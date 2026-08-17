"""inventory_links

Revision ID: 014
Revises: 013
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "drone_payload_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("drone_type_id", sa.Integer(), nullable=False),
        sa.Column("payload_type_id", sa.Integer(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("max_qty", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["drone_type_id"], ["drone_types.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payload_type_id"], ["payload_types.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("drone_type_id", "payload_type_id", name="uq_drone_payload_link"),
    )
    op.create_index(op.f("ix_drone_payload_links_id"), "drone_payload_links", ["id"], unique=False)
    op.create_index(op.f("ix_drone_payload_links_drone_type_id"), "drone_payload_links", ["drone_type_id"], unique=False)
    op.create_index(op.f("ix_drone_payload_links_payload_type_id"), "drone_payload_links", ["payload_type_id"], unique=False)

    op.create_table(
        "drone_threat_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("drone_type_id", sa.Integer(), nullable=False),
        sa.Column("threat_system_id", sa.Integer(), nullable=False),
        sa.Column("exposure_level", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["drone_type_id"], ["drone_types.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["threat_system_id"], ["threat_systems.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("drone_type_id", "threat_system_id", name="uq_drone_threat_link"),
    )
    op.create_index(op.f("ix_drone_threat_links_id"), "drone_threat_links", ["id"], unique=False)
    op.create_index(op.f("ix_drone_threat_links_drone_type_id"), "drone_threat_links", ["drone_type_id"], unique=False)
    op.create_index(op.f("ix_drone_threat_links_threat_system_id"), "drone_threat_links", ["threat_system_id"], unique=False)

    op.create_table(
        "payload_threat_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payload_type_id", sa.Integer(), nullable=False),
        sa.Column("threat_system_id", sa.Integer(), nullable=False),
        sa.Column("effectiveness", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["payload_type_id"], ["payload_types.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["threat_system_id"], ["threat_systems.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payload_type_id", "threat_system_id", name="uq_payload_threat_link"),
    )
    op.create_index(op.f("ix_payload_threat_links_id"), "payload_threat_links", ["id"], unique=False)
    op.create_index(op.f("ix_payload_threat_links_payload_type_id"), "payload_threat_links", ["payload_type_id"], unique=False)
    op.create_index(op.f("ix_payload_threat_links_threat_system_id"), "payload_threat_links", ["threat_system_id"], unique=False)


def downgrade() -> None:
    op.drop_table("payload_threat_links")
    op.drop_table("drone_threat_links")
    op.drop_table("drone_payload_links")
