"""
Last-resort restore from pg_dump .sql files in database_dumps/
(app/core/sql_dump_loader.py + its hook in backup.restore_latest_dump).
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table

from app.config import get_settings
from app.core import backup, sql_dump_loader
from app.tests.test_backup import _fake_target


def _tables():
    md = MetaData()
    users = Table("users", md, Column("id", Integer, primary_key=True), Column("username", String))
    missions = Table("missions", md, Column("id", Integer, primary_key=True), Column("name", String))
    return {"users": users, "missions": missions}


def _write_sql(path, users=(), missions=(), extra_cols=False):
    cols = "id, username, legacy_col" if extra_cols else "id, username"
    lines = [f"COPY public.users ({cols}) FROM stdin;"]
    for i, name in users:
        lines.append(f"{i}\t{name}\told" if extra_cols else f"{i}\t{name}")
    lines += ["\\.", "", "COPY public.missions (id, name) FROM stdin;"]
    lines += [f"{i}\t{name}" for i, name in missions]
    lines += ["\\.", ""]
    path.write_text("\n".join(lines))


@pytest.fixture
def sql_dir(tmp_path, monkeypatch):
    d = tmp_path / "database_dumps"
    d.mkdir()
    monkeypatch.setattr(get_settings(), "backup_sql_dump_dir", str(d))
    return d


class TestParse:
    def test_parses_rows_nulls_and_escapes(self, tmp_path):
        f = tmp_path / "d.sql"
        f.write_text("COPY public.missions (id, name) FROM stdin;\n1\tline1\\nline2\n2\t\\N\n\\.\n")
        data = sql_dump_loader.parse_sql_dump(f, _tables())
        assert data["missions"] == [{"id": 1, "name": "line1\nline2"}, {"id": 2, "name": None}]

    def test_drops_columns_the_model_no_longer_has(self, tmp_path):
        f = tmp_path / "d.sql"
        _write_sql(f, users=[(1, "bob")], extra_cols=True)
        assert sql_dump_loader.parse_sql_dump(f, _tables())["users"] == [{"id": 1, "username": "bob"}]

    def test_ignores_unknown_tables(self, tmp_path):
        f = tmp_path / "d.sql"
        f.write_text("COPY public.mystery (id) FROM stdin;\n1\n\\.\n")
        assert sql_dump_loader.parse_sql_dump(f, _tables()) == {}


class TestLoadBest:
    def test_picks_dump_with_most_rows(self, sql_dir, tmp_path):
        _write_sql(sql_dir / "small.sql", users=[(1, "a")])
        _write_sql(sql_dir / "big.sql", users=[(1, "a")], missions=[(1, "m1"), (2, "m2")])
        name, data = sql_dump_loader.load_best("main", tmp_path, _tables())
        assert name.startswith("sql:big.sql:")
        assert len(data["missions"]) == 2

    def test_applied_dump_is_not_offered_again(self, sql_dir, tmp_path):
        _write_sql(sql_dir / "d.sql", missions=[(1, "m1")])
        name, _ = sql_dump_loader.load_best("main", tmp_path, _tables())
        sql_dump_loader.mark_applied(tmp_path, name)
        assert sql_dump_loader.load_best("main", tmp_path, _tables()) is None

    def test_telemetry_and_main_use_separate_files(self, sql_dir, tmp_path):
        _write_sql(sql_dir / "da_telemetry_dump.sql", missions=[(1, "m1")])
        assert sql_dump_loader.load_best("main", tmp_path, _tables()) is None
        assert sql_dump_loader.load_best("telemetry", tmp_path, _tables()) is not None

    def test_oversized_dump_is_skipped(self, sql_dir, tmp_path, monkeypatch):
        _write_sql(sql_dir / "d.sql", missions=[(1, "m1")])
        monkeypatch.setattr(sql_dump_loader, "MAX_SQL_DUMP_BYTES", 5)
        assert sql_dump_loader.load_best("main", tmp_path, _tables()) is None

    def test_missing_directory_is_fine(self, tmp_path, monkeypatch):
        monkeypatch.setattr(get_settings(), "backup_sql_dump_dir", str(tmp_path / "nope"))
        assert sql_dump_loader.load_best("main", tmp_path, _tables()) is None

    def test_unparseable_file_is_skipped(self, sql_dir, tmp_path):
        (sql_dir / "bad.sql").write_text("COPY public.missions (id FROM stdin;\n1\n\\.\n")
        _write_sql(sql_dir / "good.sql", missions=[(1, "m1")])
        name, _ = sql_dump_loader.load_best("main", tmp_path, _tables())
        assert name.startswith("sql:good.sql:")


def _session(counts):
    """Mock DB session whose COUNT(*) answers come from `counts` in call order."""
    result = MagicMock()
    result.scalar_one.side_effect = counts
    session = AsyncMock()
    session.execute.return_value = result
    session.scalar.return_value = None
    session.__aenter__.return_value = session
    session.__aexit__.return_value = False
    return session


class TestRestoreFallback:
    async def test_restores_from_sql_when_no_json_dump_exists(self, sql_dir, tmp_path):
        _write_sql(sql_dir / "d.sql", missions=[(1, "m1")])
        tables = _tables()
        target = _fake_target(tmp_path, tables=list(tables.values()))
        # fallback gate: missions=0 -> allowed; loop: users=0, missions=0
        target.session_factory.return_value = _session([0, 0, 0])

        with patch.object(backup, "_fetch_recent_dumps", return_value=[]), \
             patch.object(backup, "broadcast_system_event", new=AsyncMock()) as ev:
            assert await backup.restore_latest_dump(target) is True

        assert ev.call_args.args[0] == "DATA_RESTORED"
        marker = json.loads((target.backup_dir / sql_dump_loader.MARKER_NAME).read_text())
        assert any(k.startswith("sql:d.sql:") for k in marker)

    async def test_not_used_when_data_tables_still_have_rows(self, sql_dir, tmp_path):
        _write_sql(sql_dir / "d.sql", users=[(1, "x")], missions=[(1, "m1")])
        tables = _tables()
        target = _fake_target(tmp_path, tables=list(tables.values()))
        # fallback gate: missions has rows (3) -> blocked; loop: users=0, missions=3
        target.session_factory.return_value = _session([3, 0, 3])

        with patch.object(backup, "_fetch_recent_dumps", return_value=[]), \
             patch.object(backup, "broadcast_system_event", new=AsyncMock()):
            assert await backup.restore_latest_dump(target) is False

        assert not (target.backup_dir / sql_dump_loader.MARKER_NAME).exists()

    async def test_still_reports_missing_when_no_sql_dump_either(self, sql_dir, tmp_path):
        target = _fake_target(tmp_path, tables=list(_tables().values()))
        with patch.object(backup, "_fetch_recent_dumps", return_value=[]), \
             patch.object(backup, "broadcast_system_event", new=AsyncMock()) as ev:
            assert await backup.restore_latest_dump(target) is False
        assert ev.call_args.args[0] == "BACKUP_MISSING"
