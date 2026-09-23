"""
Unit tests for app.core.backup — JSON table dump / auto-restore, and its
upload/rotate/restore integration with MinIO.

The real AsyncSessionLocal/TSSessionLocal (Postgres/Timescale) and each
target's backup_dir (filesystem) are redirected, and boto3's S3 client is
replaced with an in-memory fake so these tests never touch a live database,
the repo's real backups/ directories, or a network MinIO endpoint.
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


def _fake_target(tmp_path, name="main", tables=None):
    return backup.DumpTarget(
        name=name,
        metadata=MagicMock(sorted_tables=tables or []),
        session_factory=MagicMock(),
        backup_dir=tmp_path / name,
        minio_bucket=f"db-backups-{name}",
    )


class FakeS3Client:
    """In-memory stand-in for the boto3 S3 client used against MinIO."""

    def __init__(self, buckets=None):
        self.buckets: dict[str, dict[str, bytes]] = buckets if buckets is not None else {}
        self.created_buckets: list[str] = []

    def head_bucket(self, Bucket):
        if Bucket not in self.buckets:
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadBucket")

    def create_bucket(self, Bucket):
        self.buckets[Bucket] = {}
        self.created_buckets.append(Bucket)

    def upload_file(self, Filename, Bucket, Key):
        self.buckets.setdefault(Bucket, {})[Key] = open(Filename, "rb").read()

    def list_objects_v2(self, Bucket):
        objs = self.buckets.get(Bucket, {})
        return {"Contents": [{"Key": k} for k in objs]}

    def delete_object(self, Bucket, Key):
        self.buckets.get(Bucket, {}).pop(Key, None)

    def download_file(self, Bucket, Key, Filename):
        data = self.buckets[Bucket][Key]
        with open(Filename, "wb") as f:
            f.write(data)


@pytest.fixture
def fake_s3(monkeypatch):
    client = FakeS3Client()
    monkeypatch.setattr(backup, "_minio_client", lambda: client)
    return client


class TestJsonDefault:
    def test_datetime_is_isoformatted(self):
        dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert backup._json_default(dt) == dt.isoformat()

    def test_other_types_are_stringified(self):
        assert backup._json_default(123) == "123"


class TestLatestDump:
    def test_no_dumps_returns_none(self, tmp_path):
        target = _fake_target(tmp_path)
        target.backup_dir.mkdir(parents=True)
        assert backup._latest_dump(target) is None

    def test_returns_most_recent_by_sorted_name(self, tmp_path):
        target = _fake_target(tmp_path)
        target.backup_dir.mkdir(parents=True)
        (target.backup_dir / "dump_20260101T000000Z.json").write_text("{}")
        newest = target.backup_dir / "dump_20260102T000000Z.json"
        newest.write_text("{}")
        assert backup._latest_dump(target) == newest


class TestUploadToMinio:
    def test_creates_bucket_and_uploads(self, tmp_path, fake_s3):
        target = _fake_target(tmp_path)
        target.backup_dir.mkdir(parents=True)
        dump_path = target.backup_dir / "dump_20260101T000000Z.json"
        dump_path.write_text(json.dumps({"users": []}))

        backup._upload_to_minio(target, dump_path, dump_path.name)

        assert target.minio_bucket in fake_s3.created_buckets
        assert dump_path.name in fake_s3.buckets[target.minio_bucket]

    def test_upload_failure_is_swallowed(self, tmp_path, monkeypatch):
        target = _fake_target(tmp_path)
        target.backup_dir.mkdir(parents=True)
        dump_path = target.backup_dir / "dump_20260101T000000Z.json"
        dump_path.write_text("{}")

        from botocore.exceptions import BotoCoreError

        class BrokenClient:
            def head_bucket(self, Bucket):
                raise BotoCoreError()

            def create_bucket(self, Bucket):
                raise BotoCoreError()

        monkeypatch.setattr(backup, "_minio_client", lambda: BrokenClient())

        # Must not raise — callers treat a MinIO failure as non-fatal.
        backup._upload_to_minio(target, dump_path, dump_path.name)


class TestRotateOldDumps:
    def test_keeps_dumps_within_retention_count(self, tmp_path, monkeypatch, fake_s3):
        monkeypatch.setattr(backup.cfg, "backup_retention_count", 2)
        target = _fake_target(tmp_path)
        target.backup_dir.mkdir(parents=True)
        for i in range(2):
            (target.backup_dir / f"dump_2026010{i}T000000Z.json").write_text("{}")

        backup._rotate_old_dumps(target)
        assert len(list(target.backup_dir.glob("dump_*.json"))) == 2

    def test_deletes_oldest_beyond_retention_count(self, tmp_path, monkeypatch, fake_s3):
        monkeypatch.setattr(backup.cfg, "backup_retention_count", 1)
        target = _fake_target(tmp_path)
        target.backup_dir.mkdir(parents=True)
        oldest = target.backup_dir / "dump_20260101T000000Z.json"
        oldest.write_text("{}")
        newest = target.backup_dir / "dump_20260102T000000Z.json"
        newest.write_text("{}")

        backup._rotate_old_dumps(target)

        remaining = list(target.backup_dir.glob("dump_*.json"))
        assert remaining == [newest]
        assert not oldest.exists()

    def test_also_rotates_old_dumps_in_minio(self, tmp_path, monkeypatch, fake_s3):
        monkeypatch.setattr(backup.cfg, "backup_retention_count", 1)
        target = _fake_target(tmp_path)
        target.backup_dir.mkdir(parents=True)
        fake_s3.buckets[target.minio_bucket] = {
            "dump_20260101T000000Z.json": b"{}",
            "dump_20260102T000000Z.json": b"{}",
        }

        backup._rotate_old_dumps(target)

        remaining_keys = set(fake_s3.buckets[target.minio_bucket])
        assert remaining_keys == {"dump_20260102T000000Z.json"}


class TestFetchRecentDumps:
    def test_prefers_minio_and_downloads_missing_locally(self, tmp_path, fake_s3):
        target = _fake_target(tmp_path)
        target.backup_dir.mkdir(parents=True)
        fake_s3.buckets[target.minio_bucket] = {
            "dump_20260101T000000Z.json": json.dumps({"users": [{"id": 1}]}).encode(),
        }

        fetched = backup._fetch_recent_dumps(target, limit=5)

        assert len(fetched) == 1
        path, name = fetched[0]
        assert name == "dump_20260101T000000Z.json"
        assert path.exists()
        assert json.loads(path.read_text()) == {"users": [{"id": 1}]}

    def test_falls_back_to_local_when_minio_empty(self, tmp_path, fake_s3):
        target = _fake_target(tmp_path)
        target.backup_dir.mkdir(parents=True)
        local_dump = target.backup_dir / "dump_20260101T000000Z.json"
        local_dump.write_text(json.dumps({"users": []}))

        fetched = backup._fetch_recent_dumps(target, limit=5)

        assert fetched == [(local_dump, local_dump.name)]

    def test_falls_back_to_local_when_minio_unreachable(self, tmp_path, monkeypatch):
        target = _fake_target(tmp_path)
        target.backup_dir.mkdir(parents=True)
        local_dump = target.backup_dir / "dump_20260101T000000Z.json"
        local_dump.write_text(json.dumps({"users": []}))

        from botocore.exceptions import BotoCoreError

        class BrokenClient:
            def head_bucket(self, Bucket):
                raise BotoCoreError()

            def create_bucket(self, Bucket):
                raise BotoCoreError()

            def list_objects_v2(self, Bucket):
                raise BotoCoreError()

        monkeypatch.setattr(backup, "_minio_client", lambda: BrokenClient())

        fetched = backup._fetch_recent_dumps(target, limit=5)
        assert fetched == [(local_dump, local_dump.name)]


class TestCreateDump:
    async def test_writes_json_locally_and_uploads_to_minio(self, tmp_path, fake_s3):
        fake_table = _fake_table("users")
        target = _fake_target(tmp_path, tables=[fake_table])

        fake_result = MagicMock()
        fake_row = MagicMock()
        fake_row._mapping = {"id": 1, "username": "admin"}
        fake_result.fetchall.return_value = [fake_row]

        fake_session = AsyncMock()
        fake_session.execute.return_value = fake_result
        fake_session.__aenter__.return_value = fake_session
        fake_session.__aexit__.return_value = False
        target.session_factory.return_value = fake_session

        dump_path = await backup.create_dump(target)

        assert dump_path.exists()
        data = json.loads(dump_path.read_text())
        assert data == {"users": [{"id": 1, "username": "admin"}]}

        # Confirms the dump actually reached MinIO, not just local disk.
        assert dump_path.name in fake_s3.buckets[target.minio_bucket]
        uploaded = json.loads(fake_s3.buckets[target.minio_bucket][dump_path.name])
        assert uploaded == data

    async def test_incremental_dump_carries_forward_untouched_tables(self, tmp_path, fake_s3):
        fake_table = _fake_table("users")
        target = _fake_target(tmp_path, tables=[fake_table])
        target.backup_dir.mkdir(parents=True)
        previous = target.backup_dir / "dump_20260101T000000Z.json"
        previous.write_text(json.dumps({"users": [{"id": 1, "username": "old"}]}))

        fake_result = MagicMock()
        fake_result.fetchall.return_value = []
        fake_session = AsyncMock()
        fake_session.execute.return_value = fake_result
        fake_session.__aenter__.return_value = fake_session
        fake_session.__aexit__.return_value = False
        target.session_factory.return_value = fake_session

        # Re-read no tables — everything should carry over from `previous`.
        dump_path = await backup.create_dump(target, tables=set())

        data = json.loads(dump_path.read_text())
        assert data == {"users": [{"id": 1, "username": "old"}]}

    async def test_rotates_after_creating(self, tmp_path, fake_s3):
        target = _fake_target(tmp_path, tables=[])
        fake_result = MagicMock()
        fake_result.fetchall.return_value = []
        fake_session = AsyncMock()
        fake_session.execute.return_value = fake_result
        fake_session.__aenter__.return_value = fake_session
        fake_session.__aexit__.return_value = False
        target.session_factory.return_value = fake_session

        with patch.object(backup, "_rotate_old_dumps") as mock_rotate:
            await backup.create_dump(target)

        mock_rotate.assert_called_once_with(target)


class TestRestoreLatestDump:
    async def test_no_dump_anywhere_returns_false_and_broadcasts_missing(self, tmp_path, fake_s3):
        target = _fake_target(tmp_path, tables=[])
        with patch.object(backup, "broadcast_system_event", new=AsyncMock()) as mock_broadcast:
            result = await backup.restore_latest_dump(target)

        assert result is False
        mock_broadcast.assert_awaited_once()
        assert mock_broadcast.call_args.args[0] == "BACKUP_MISSING"

    async def test_restores_from_minio_dump_and_broadcasts(self, tmp_path, fake_s3):
        fake_table = _fake_table("users")
        target = _fake_target(tmp_path, tables=[fake_table])
        target.backup_dir.mkdir(parents=True)
        fake_s3.buckets[target.minio_bucket] = {
            "dump_20260101T000000Z.json": json.dumps(
                {"users": [{"id": 1, "username": "admin"}]}
            ).encode(),
        }

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        fake_session = AsyncMock()
        fake_session.execute.return_value = count_result
        fake_session.scalar.return_value = None
        fake_session.__aenter__.return_value = fake_session
        fake_session.__aexit__.return_value = False
        target.session_factory.return_value = fake_session

        with patch.object(backup, "broadcast_system_event", new=AsyncMock()) as mock_broadcast:
            result = await backup.restore_latest_dump(target)

        assert result is True
        fake_session.commit.assert_awaited_once()
        mock_broadcast.assert_awaited_once()
        assert mock_broadcast.call_args.args[0] == "DATA_RESTORED"

    async def test_skips_tables_that_already_have_rows(self, tmp_path, fake_s3):
        fake_table = _fake_table("users")
        target = _fake_target(tmp_path, tables=[fake_table])
        target.backup_dir.mkdir(parents=True)
        fake_s3.buckets[target.minio_bucket] = {
            "dump_20260101T000000Z.json": json.dumps(
                {"users": [{"id": 1, "username": "admin"}]}
            ).encode(),
        }

        count_result = MagicMock()
        count_result.scalar_one.return_value = 5  # already has data
        fake_session = AsyncMock()
        fake_session.execute.return_value = count_result
        fake_session.__aenter__.return_value = fake_session
        fake_session.__aexit__.return_value = False
        target.session_factory.return_value = fake_session

        with patch.object(backup, "broadcast_system_event", new=AsyncMock()), \
             patch.object(fake_table, "insert", wraps=fake_table.insert) as spy_insert:
            result = await backup.restore_latest_dump(target)

        assert result is False
        spy_insert.assert_not_called()

    async def test_walks_back_through_history_for_table_with_data(self, tmp_path, fake_s3):
        """A dump taken right after partial data loss only has empty arrays for
        the lost table — restore must look further back to find real rows."""
        fake_table = _fake_table("users")
        target = _fake_target(tmp_path, tables=[fake_table])
        target.backup_dir.mkdir(parents=True)
        fake_s3.buckets[target.minio_bucket] = {
            "dump_20260101T000000Z.json": json.dumps(
                {"users": [{"id": 1, "username": "admin"}]}
            ).encode(),
            "dump_20260102T000000Z.json": json.dumps({"users": []}).encode(),
        }

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        fake_session = AsyncMock()
        fake_session.execute.return_value = count_result
        fake_session.scalar.return_value = None
        fake_session.__aenter__.return_value = fake_session
        fake_session.__aexit__.return_value = False
        target.session_factory.return_value = fake_session

        with patch.object(backup, "broadcast_system_event", new=AsyncMock()) as mock_broadcast:
            result = await backup.restore_latest_dump(target)

        assert result is True
        assert "dump_20260101T000000Z.json" in mock_broadcast.call_args.kwargs["dump_file"]


class TestTablesWithExpectedDataAreEmpty:
    async def test_no_dump_returns_false(self, tmp_path, fake_s3):
        target = _fake_target(tmp_path, tables=[])
        result = await backup._tables_with_expected_data_are_empty(AsyncMock(), target)
        assert result is False

    async def test_dump_with_no_rows_anywhere_returns_false(self, tmp_path, fake_s3):
        target = _fake_target(tmp_path, tables=[])
        target.backup_dir.mkdir(parents=True)
        fake_s3.buckets[target.minio_bucket] = {
            "dump_20260101T000000Z.json": json.dumps({"users": []}).encode(),
        }
        result = await backup._tables_with_expected_data_are_empty(AsyncMock(), target)
        assert result is False

    async def test_all_tables_empty_returns_true(self, tmp_path, fake_s3):
        target = _fake_target(tmp_path, tables=[])
        target.backup_dir.mkdir(parents=True)
        fake_s3.buckets[target.minio_bucket] = {
            "dump_20260101T000000Z.json": json.dumps({"users": [{"id": 1}]}).encode(),
        }
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        fake_db = AsyncMock()
        fake_db.execute.return_value = count_result

        result = await backup._tables_with_expected_data_are_empty(fake_db, target)
        assert result is True

    async def test_any_table_with_rows_returns_false(self, tmp_path, fake_s3):
        target = _fake_target(tmp_path, tables=[])
        target.backup_dir.mkdir(parents=True)
        fake_s3.buckets[target.minio_bucket] = {
            "dump_20260101T000000Z.json": json.dumps(
                {"users": [{"id": 1}], "missions": [{"id": 2}]}
            ).encode(),
        }
        count_result = MagicMock()
        count_result.scalar_one.return_value = 3  # non-empty
        fake_db = AsyncMock()
        fake_db.execute.return_value = count_result

        result = await backup._tables_with_expected_data_are_empty(fake_db, target)
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
                await backup.run_backup_scheduler(backup.MAIN_TARGET)

        mock_create_dump.assert_awaited_once_with(backup.MAIN_TARGET)

    async def test_exception_in_create_dump_is_logged_and_loop_continues(self, monkeypatch):
        monkeypatch.setattr(backup.cfg, "backup_interval_minutes", 1)
        mock_create_dump = AsyncMock(side_effect=RuntimeError("boom"))

        async def fake_sleep(_):
            raise asyncio.CancelledError()

        with patch.object(backup, "create_dump", mock_create_dump), \
             patch.object(backup.asyncio, "sleep", fake_sleep):
            with pytest.raises(asyncio.CancelledError):
                await backup.run_backup_scheduler(backup.MAIN_TARGET)

        mock_create_dump.assert_awaited_once()


class TestRunIntegrityMonitor:
    async def test_no_data_loss_does_not_restore(self, monkeypatch):
        monkeypatch.setattr(backup.cfg, "integrity_check_interval_minutes", 1)

        sleep_calls = {"count": 0}

        async def fake_sleep(_):
            sleep_calls["count"] += 1
            if sleep_calls["count"] >= 2:
                raise asyncio.CancelledError()

        with patch.object(backup, "check_and_restore_if_lost", AsyncMock(return_value=False)) as mock_check, \
             patch.object(backup.asyncio, "sleep", fake_sleep):
            with pytest.raises(asyncio.CancelledError):
                await backup.run_integrity_monitor(backup.MAIN_TARGET)

        mock_check.assert_awaited_once_with(backup.MAIN_TARGET)

    async def test_exception_during_check_is_swallowed_and_loop_continues(self, tmp_path, monkeypatch):
        """check_and_restore_if_lost() itself catches errors (e.g. DB down) —
        confirm that keeps the outer loop alive rather than crashing it."""
        monkeypatch.setattr(backup.cfg, "integrity_check_interval_minutes", 1)
        target = _fake_target(tmp_path, tables=[])
        target.session_factory.side_effect = RuntimeError("db down")

        sleep_calls = {"count": 0}

        async def fake_sleep(_):
            sleep_calls["count"] += 1
            if sleep_calls["count"] >= 2:
                raise asyncio.CancelledError()

        with patch.object(backup.asyncio, "sleep", fake_sleep):
            with pytest.raises(asyncio.CancelledError):
                await backup.run_integrity_monitor(target)

        assert sleep_calls["count"] == 2
