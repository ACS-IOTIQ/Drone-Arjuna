"""Tamper-evident audit log: hash chain + immutability trigger

Revision ID: 016
Revises: 015
Create Date: 2026-10-03 12:00:00

* prev_hash / row_hash form a SHA-256 chain over every record, so a modified,
  removed or re-ordered row is detectable (see verify_audit_chain()).
* A trigger rejects UPDATE, DELETE and TRUNCATE for every role, including the
  application's. Only someone able to drop the trigger (a DB owner/superuser)
  can alter history, and doing so breaks the chain.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_log", sa.Column("prev_hash", sa.String(64), nullable=True))
    op.add_column("audit_log", sa.Column("row_hash", sa.String(64), nullable=True))
    op.execute("""
        CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only (% blocked)', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER audit_log_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
    """)
    op.execute("""
        CREATE TRIGGER audit_log_no_truncate
        BEFORE TRUNCATE ON audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION audit_log_immutable();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_immutable()")
    op.drop_column("audit_log", "row_hash")
    op.drop_column("audit_log", "prev_hash")
