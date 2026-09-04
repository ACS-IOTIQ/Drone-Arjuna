"""
Unit tests for app.core.backup — JSON table dump / auto-restore.

The real AsyncSessionLocal (Postgres) and BACKUP_DIR (filesystem) are both
mocked/redirected so these tests never touch a live database or the repo's
real backups/ directory.
"""
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table

from app.core import backup


def _fake_table(name="users"):
    return Table(name, MetaData(), Column("id", Integer, primary_key=True), Column("username", String))


@pytest.fixture(autouse=True)
def _isolated_backup_dir(tmp_path, monkeypatch):
    """Redirect BACKUP_DIR to a per-test temp directory, and stub out MinIO
    entirely so tests never touch the network — the real client would try to
    resolve the `minio` Docker DNS name and hang/fail outside the container."""
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(backup, "_upload_to_minio", lambda *a, **k: None)
    monkeypatch.setattr(backup, "_rotate_old_minio_dumps", lambda: None)
    monkeypatch.setattr(backup, "_latest_dump_key_from_minio", lambda: None)
    yield tmp_path


def _make_dump_file(dir_path, stamp, data):
    path = dir_path / f"dump_{stamp}.json"
    path.write_text(json.dumps(data))
    return path


class TestJsonDefault:
    def test_datetime_is_isoformatted(self):
        dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert backup._json_default(dt) == dt.isoformat()

    def test_other_types_are_stringified(self):
        assert backup._json_default(123) == "123"


class TestLatestDump:
    def test_no_dumps_returns_none(self, _isolated_backup_dir):
        assert backup._latest_dump() is None

    def test_returns_most_recent_by_sorted_name(self, _isolated_backup_dir):
        _make_dump_file(_isolated_backup_dir, "20260101T000000Z", {})
        newest = _make_dump_file(_isolated_backup_dir, "20260102T000000Z", {})
        assert backup._latest_dump() == newest


class TestRotateOldDumps:
    def test_keeps_dumps_within_retention_count(self, _isolated_backup_dir, monkeypatch):
        monkeypatch.setattr(backup.cfg, "backup_retention_count", 2)
        for i in range(2):
            _make_dump_file(_isolated_backup_dir, f"2026010{i}T000000Z", {})
        backup._rotate_old_dumps()
        assert len(list(_isolated_backup_dir.glob("dump_*.json"))) == 2

    def test_deletes_oldest_beyond_retention_count(self, _isolated_backup_dir, monkeypatch):
        monkeypatch.setattr(backup.cfg, "backup_retention_count", 1)
        oldest = _make_dump_file(_isolated_backup_dir, "20260101T000000Z", {})
        newest = _make_dump_file(_isolated_backup_dir, "20260102T000000Z", {})
        backup._rotate_old_dumps()
        remaining = list(_isolated_backup_dir.glob("dump_*.json"))
        assert remaining == [newest]
        assert not oldest.exists()


class TestCreateDump:
    async def test_creates_backup_dir_and_writes_json(self, _isolated_backup_dir):
        fake_table = _fake_table("users")

        fake_result = MagicMock()
        fake_row = MagicMock()
        fake_row._mapping = {"id": 1, "username": "admin"}
        fake_result.fetchall.return_value = [fake_row]

        fake_session = AsyncMock()
        fake_session.execute.return_value = fake_result
        fake_session.__aenter__.return_value = fake_session
        fake_session.__aexit__.return_value = False

        with patch.object(backup, "AsyncSessionLocal", return_value=fake_session), \
             patch.object(backup, "Base", MagicMock(metadata=MagicMock(sorted_tables=[fake_table]))):
            dump_path = await backup.create_dump()

        assert dump_path.exists()
        data = json.loads(dump_path.read_text())
        assert data == {"users": [{"id": 1, "username": "admin"}]}

    async def test_rotates_after_creating(self, _isolated_backup_dir):
        fake_session = AsyncMock()
        fake_result = MagicMock()
        fake_result.fetchall.return_value = []
        fake_session.execute.return_value = fake_result
        fake_session.__aenter__.return_value = fake_session
        fake_session.__aexit__.return_value = False

        with patch.object(backup, "AsyncSessionLocal", return_value=fake_session), \
             patch.object(backup, "Base", MagicMock(metadata=MagicMock(sorted_tables=[]))), \
             patch.object(backup, "_rotate_old_dumps") as mock_rotate:
            await backup.create_dump()

        mock_rotate.assert_called_once()


class TestRestoreLatestDump:
    async def test_no_dump_file_returns_false(self, _isolated_backup_dir):
        result = await backup.restore_latest_dump()
        assert result is False

    async def test_restores_empty_tables_and_broadcasts(self, _isolated_backup_dir):
        _make_dump_file(
            _isolated_backup_dir, "20260101T000000Z",
            {"users": [{"id": 1, "username": "admin"}]},
        )
        fake_table = _fake_table("users")

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        fake_session = AsyncMock()
        fake_session.execute.return_value = count_result
        fake_session.__aenter__.return_value = fake_session
        fake_session.__aexit__.return_value = False

        with patch.object(backup, "AsyncSessionLocal", return_value=fake_session), \
             patch.object(backup, "Base", MagicMock(metadata=MagicMock(sorted_tables=[fake_table]))), \
             patch.object(backup, "broadcast_system_event", new=AsyncMock()) as mock_broadcast:
            result = await backup.restore_latest_dump()

        assert result is True
        fake_session.commit.assert_awaited_once()
        mock_broadcast.assert_awaited_once()
        assert mock_broadcast.call_args.args[0] == "DATA_RESTORED"

    async def test_skips_tables_that_already_have_rows(self, _isolated_backup_dir):
        _make_dump_file(
            _isolated_backup_dir, "20260101T000000Z",
            {"users": [{"id": 1, "username": "admin"}]},
        )
        fake_table = _fake_table("users")

        count_result = MagicMock()
        count_result.scalar_one.return_value = 5  # already has data

        fake_session = AsyncMock()
        fake_session.execute.return_value = count_result
        fake_session.__aenter__.return_value = fake_session
        fake_session.__aexit__.return_value = False

        with patch.object(backup, "AsyncSessionLocal", return_value=fake_session), \
             patch.object(backup, "Base", MagicMock(metadata=MagicMock(sorted_tables=[fake_table]))), \
             patch.object(backup, "broadcast_system_event", new=AsyncMock()), \
             patch.object(fake_table, "insert", wraps=fake_table.insert) as spy_insert:
            await backup.restore_latest_dump()

        spy_insert.assert_not_called()

    async def test_skips_tables_with_no_rows_in_dump(self, _isolated_backup_dir):
        _make_dump_file(_isolated_backup_dir, "20260101T000000Z", {"users": []})
        fake_table = _fake_table("users")

        fake_session = AsyncMock()
        fake_session.__aenter__.return_value = fake_session
        fake_session.__aexit__.return_value = False

        with patch.object(backup, "AsyncSessionLocal", return_value=fake_session), \
             patch.object(backup, "Base", MagicMock(metadata=MagicMock(sorted_tables=[fake_table]))), \
             patch.object(backup, "broadcast_system_event", new=AsyncMock()):
            await backup.restore_latest_dump()

        # No COUNT(*) query should be needed for a table with zero dumped rows
        fake_session.execute.assert_not_called()


class TestTablesWithExpectedDataAreEmpty:
    async def test_no_dump_returns_false(self, _isolated_backup_dir):
        result = await backup._tables_with_expected_data_are_empty(AsyncMock())
        assert result is False

    async def test_dump_with_no_rows_anywhere_returns_false(self, _isolated_backup_dir):
        _make_dump_file(_isolated_backup_dir, "20260101T000000Z", {"users": []})
        result = await backup._tables_with_expected_data_are_empty(AsyncMock())
        assert result is False

    async def test_all_tables_empty_returns_true(self, _isolated_backup_dir):
        _make_dump_file(
            _isolated_backup_dir, "20260101T000000Z",
            {"users": [{"id": 1}]},
        )
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        fake_db = AsyncMock()
        fake_db.execute.return_value = count_result

        result = await backup._tables_with_expected_data_are_empty(fake_db)
        assert result is True

    async def test_any_table_with_rows_returns_false(self, _isolated_backup_dir):
        _make_dump_file(
            _isolated_backup_dir, "20260101T000000Z",
            {"users": [{"id": 1}], "missions": [{"id": 2}]},
        )
        count_result = MagicMock()
        count_result.scalar_one.return_value = 3  # non-empty
        fake_db = AsyncMock()
        fake_db.execute.return_value = count_result

        result = await backup._tables_with_expected_data_are_empty(fake_db)
        assert result is False


class TestRunBackupScheduler:
    async def test_loop_calls_create_dump_then_sleeps(self, monkeypatch):
        monkeypatch.setattr(backup.cfg, "backup_interval_minutes", 1)
        mock_create_dump = AsyncMock()

        call_count = {"sleep": 0}

        async def fake_sleep(_):
            call_count["sleep"] += 1
            if call_count["sleep"] >= 1:
                raise asyncio.CancelledError()

        with patch.object(backup, "create_dump", mock_create_dump), \
             patch.object(backup.asyncio, "sleep", fake_sleep):
            with pytest.raises(asyncio.CancelledError):
                await backup.run_backup_scheduler()

        mock_create_dump.assert_awaited_once()

    async def test_exception_in_create_dump_is_logged_and_loop_continues(self, monkeypatch):
        monkeypatch.setattr(backup.cfg, "backup_interval_minutes", 1)
        mock_create_dump = AsyncMock(side_effect=RuntimeError("boom"))

        async def fake_sleep(_):
            raise asyncio.CancelledError()

        with patch.object(backup, "create_dump", mock_create_dump), \
             patch.object(backup.asyncio, "sleep", fake_sleep):
            with pytest.raises(asyncio.CancelledError):
                await backup.run_backup_scheduler()

        mock_create_dump.assert_awaited_once()


class TestRunIntegrityMonitor:
    async def test_no_data_loss_does_not_restore(self, monkeypatch):
        monkeypatch.setattr(backup.cfg, "integrity_check_interval_minutes", 1)

        fake_session = AsyncMock()
        fake_session.__aenter__.return_value = fake_session
        fake_session.__aexit__.return_value = False

        sleep_calls = {"count": 0}

        async def fake_sleep(_):
            sleep_calls["count"] += 1
            if sleep_calls["count"] >= 2:
                raise asyncio.CancelledError()

        with patch.object(backup, "AsyncSessionLocal", return_value=fake_session), \
             patch.object(backup, "_tables_with_expected_data_are_empty", AsyncMock(return_value=False)), \
             patch.object(backup, "restore_latest_dump", AsyncMock()) as mock_restore, \
             patch.object(backup.asyncio, "sleep", fake_sleep):
            with pytest.raises(asyncio.CancelledError):
                await backup.run_integrity_monitor()

        mock_restore.assert_not_awaited()

    async def test_data_loss_detected_triggers_restore_and_broadcast(self, monkeypatch):
        monkeypatch.setattr(backup.cfg, "integrity_check_interval_minutes", 1)

        fake_session = AsyncMock()
        fake_session.__aenter__.return_value = fake_session
        fake_session.__aexit__.return_value = False

        sleep_calls = {"count": 0}

        async def fake_sleep(_):
            sleep_calls["count"] += 1
            if sleep_calls["count"] >= 2:
                raise asyncio.CancelledError()

        with patch.object(backup, "AsyncSessionLocal", return_value=fake_session), \
             patch.object(backup, "_tables_with_expected_data_are_empty", AsyncMock(return_value=True)), \
             patch.object(backup, "restore_latest_dump", AsyncMock()) as mock_restore, \
             patch.object(backup, "broadcast_system_event", AsyncMock()) as mock_broadcast, \
             patch.object(backup.asyncio, "sleep", fake_sleep):
            with pytest.raises(asyncio.CancelledError):
                await backup.run_integrity_monitor()

        mock_restore.assert_awaited_once()
        mock_broadcast.assert_awaited_once()
        assert mock_broadcast.call_args.args[0] == "DATA_LOSS_DETECTED"

    async def test_exception_during_check_is_logged_and_loop_continues(self, monkeypatch):
        monkeypatch.setattr(backup.cfg, "integrity_check_interval_minutes", 1)

        sleep_calls = {"count": 0}

        async def fake_sleep(_):
            sleep_calls["count"] += 1
            if sleep_calls["count"] >= 2:
                raise asyncio.CancelledError()

        with patch.object(backup, "AsyncSessionLocal", side_effect=RuntimeError("db down")), \
             patch.object(backup.asyncio, "sleep", fake_sleep):
            with pytest.raises(asyncio.CancelledError):
                await backup.run_integrity_monitor()

        # The loop must survive the exception and reach its second sleep
        assert sleep_calls["count"] == 2
