"""L-01: table names read from a dump file are data, never SQL."""
import json
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import table as sa_table

from app.core import backup

EVIL = 'users"; DROP TABLE users; --'


def _target(tmp_path, tables):
    return backup.DumpTarget(
        name="main",
        metadata=MagicMock(sorted_tables=tables),
        session_factory=MagicMock(),
        backup_dir=tmp_path / "main",
        minio_bucket="db-backups-main",
    )


async def test_hostile_table_name_in_legacy_dump_is_never_queried(tmp_path, monkeypatch):
    target = _target(tmp_path, [sa_table("users")])
    target.backup_dir.mkdir(parents=True)
    dump = target.backup_dir / "dump_20260101T000000Z.json"
    dump.write_text(json.dumps({EVIL: [{"id": 1}]}))             # unsigned legacy-style dump
    monkeypatch.setattr(backup, "_fetch_recent_dumps", lambda t, n: [(dump, dump.name)])

    db = AsyncMock()
    assert await backup._tables_with_expected_data_are_empty(db, target) is False
    db.execute.assert_not_awaited()                                # nothing was sent to the DB


async def test_row_count_uses_a_sqlalchemy_construct_not_a_string():
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one.return_value = 7
    db.execute.return_value = result
    assert await backup._row_count(db, sa_table("users")) == 7
    statement = db.execute.await_args.args[0]
    assert not isinstance(statement, str)
    assert "COUNT" in str(statement).upper()
