"""
Database backup / auto-restore.

Periodically dumps every table under `Base.metadata` (the main PostgreSQL
database — missions, drones, users, etc.) to timestamped JSON files, and
periodically checks whether tables that should have data are empty. If
they are, the most recent dump is restored automatically.

Deliberately implemented with plain SQLAlchemy row dumps instead of shelling
out to `pg_dump`/`psql` (those binaries aren't in the backend image, and this
keeps the whole thing async and dependency-free).

Dumps are written to local disk (fast, simple restore path) and then
uploaded to the `db-backups` bucket in MinIO (durable, survives the backend
container/volume being wiped). Restore prefers the newest object in MinIO
and falls back to the newest local file if MinIO is unreachable.
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
import structlog
from sqlalchemy import Date, DateTime, select, text

from app.config import get_settings
from app.database import Base, AsyncSessionLocal
from app.core.system_events import broadcast_system_event

log = structlog.get_logger()
cfg = get_settings()

BACKUP_DIR = Path(__file__).resolve().parent.parent.parent / "backups"
MINIO_BUCKET = "db-backups"

# Fail fast rather than hang (e.g. MinIO unreachable, DNS name only resolves
# inside the Docker network) — callers treat a connection failure the same
# as "no backup available yet" and fall back to local disk.
_BOTO_CONFIG = BotoConfig(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1})


def _minio_client():
    return boto3.client(
        "s3",
        endpoint_url=f"http{'s' if cfg.minio_secure else ''}://{cfg.minio_endpoint}",
        aws_access_key_id=cfg.minio_user,
        aws_secret_access_key=cfg.minio_password,
        config=_BOTO_CONFIG,
    )


def _ensure_bucket(client):
    try:
        client.head_bucket(Bucket=MINIO_BUCKET)
    except (BotoCoreError, ClientError):
        client.create_bucket(Bucket=MINIO_BUCKET)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _restore_rows(table, rows: list[dict]) -> list[dict]:
    """Convert JSON-encoded temporal values back to database-native values."""
    temporal_columns = {
        column.name: column.type
        for column in table.columns
        if isinstance(column.type, (DateTime, Date))
    }
    restored = []
    for row in rows:
        converted = dict(row)
        for column_name, column_type in temporal_columns.items():
            value = converted.get(column_name)
            if isinstance(value, str):
                converted[column_name] = (
                    datetime.fromisoformat(value)
                    if isinstance(column_type, DateTime)
                    else datetime.fromisoformat(value).date()
                )
        restored.append(converted)
    return restored


async def create_dump() -> Path:
    """Dump every table's rows to a single timestamped JSON file, then upload it to MinIO."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dump_name = f"dump_{stamp}.json"
    dump_path = BACKUP_DIR / dump_name

    data = {}
    async with AsyncSessionLocal() as db:
        for table in Base.metadata.sorted_tables:
            result = await db.execute(select(table))
            rows = [dict(row._mapping) for row in result.fetchall()]
            data[table.name] = rows

    dump_path.write_text(json.dumps(data, default=_json_default, indent=2))
    log.info("Database dump created", path=str(dump_path), tables=len(data))

    _upload_to_minio(dump_path, dump_name)
    _rotate_old_dumps()
    return dump_path


def _upload_to_minio(dump_path: Path, dump_name: str):
    try:
        client = _minio_client()
        _ensure_bucket(client)
        client.upload_file(str(dump_path), MINIO_BUCKET, dump_name)
        log.info("Database dump uploaded to MinIO", bucket=MINIO_BUCKET, key=dump_name)
    except (BotoCoreError, ClientError) as e:
        log.error("Failed to upload dump to MinIO", error=str(e))


def _rotate_old_dumps():
    dumps = sorted(BACKUP_DIR.glob("dump_*.json"))
    excess = len(dumps) - cfg.backup_retention_count
    for stale in dumps[:excess]:
        stale.unlink(missing_ok=True)
        log.info("Rotated old dump", path=str(stale))

    _rotate_old_minio_dumps()


def _rotate_old_minio_dumps():
    try:
        client = _minio_client()
        _ensure_bucket(client)
        keys = sorted(
            obj["Key"] for obj in client.list_objects_v2(Bucket=MINIO_BUCKET).get("Contents", [])
        )
        excess = len(keys) - cfg.backup_retention_count
        for stale_key in keys[:excess]:
            client.delete_object(Bucket=MINIO_BUCKET, Key=stale_key)
            log.info("Rotated old dump from MinIO", key=stale_key)
    except (BotoCoreError, ClientError) as e:
        log.error("Failed to rotate dumps in MinIO", error=str(e))


def _latest_dump_key_from_minio() -> str | None:
    try:
        client = _minio_client()
        _ensure_bucket(client)
        keys = sorted(
            obj["Key"] for obj in client.list_objects_v2(Bucket=MINIO_BUCKET).get("Contents", [])
        )
        return keys[-1] if keys else None
    except (BotoCoreError, ClientError) as e:
        log.error("Failed to list dumps in MinIO", error=str(e))
        return None


def _latest_dump() -> Path | None:
    dumps = sorted(BACKUP_DIR.glob("dump_*.json"))
    return dumps[-1] if dumps else None


def _fetch_latest_dump() -> tuple[Path, str] | None:
    """
    Resolve the newest dump, preferring MinIO (durable) over local disk (which
    may have been wiped along with the postgres volume). Downloads the MinIO
    object to BACKUP_DIR if it isn't already present locally.
    """
    minio_key = _latest_dump_key_from_minio()
    if minio_key is not None:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        local_path = BACKUP_DIR / minio_key
        if not local_path.exists():
            try:
                client = _minio_client()
                client.download_file(MINIO_BUCKET, minio_key, str(local_path))
                log.info("Downloaded dump from MinIO", key=minio_key)
            except (BotoCoreError, ClientError) as e:
                log.error("Failed to download dump from MinIO", key=minio_key, error=str(e))
                local_path = None
        if local_path is not None and local_path.exists():
            return local_path, minio_key

    local_fallback = _latest_dump()
    if local_fallback is not None:
        return local_fallback, local_fallback.name
    return None


async def restore_latest_dump() -> bool:
    """Restore every table that is currently empty from the newest dump (MinIO, or local disk)."""
    fetched = await asyncio.to_thread(_fetch_latest_dump)
    if fetched is None:
        log.warning("Restore requested but no dump exists in MinIO or on disk")
        return False
    dump_path, dump_name = fetched

    data = await asyncio.to_thread(
        lambda: json.loads(dump_path.read_text())
    )

    async with AsyncSessionLocal() as db:
        for table in Base.metadata.sorted_tables:
            rows = data.get(table.name) or []
            if not rows:
                continue
            count = (await db.execute(
                text(f'SELECT COUNT(*) FROM "{table.name}"')
            )).scalar_one()
            if count > 0:
                continue
            await db.execute(table.insert(), _restore_rows(table, rows))
            log.info("Restored table from dump", table=table.name, rows=len(rows))
        await db.commit()

    log.info("Database restore complete", path=str(dump_path))
    await broadcast_system_event(
        "DATA_RESTORED",
        "Data loss was detected and the database was automatically restored from the latest backup.",
        dump_file=dump_name,
    )
    return True


async def _tables_with_expected_data_are_empty(db) -> bool:
    """True if a dump exists but every table it covers is currently empty."""
    fetched = _fetch_latest_dump()
    if fetched is None:
        return False
    dump_path, _ = fetched
    data = json.loads(dump_path.read_text())
    had_any_rows_in_dump = any(rows for rows in data.values())
    if not had_any_rows_in_dump:
        return False

    for table_name, rows in data.items():
        if not rows:
            continue
        count = (await db.execute(
            text(f'SELECT COUNT(*) FROM "{table_name}"')
        )).scalar_one()
        if count > 0:
            return False
    return True


async def run_backup_scheduler():
    """Background loop: dump the database on a fixed interval."""
    interval = cfg.backup_interval_minutes * 60
    while True:
        try:
            await create_dump()
        except Exception as e:
            log.error("Scheduled backup failed", error=str(e))
        await asyncio.sleep(interval)


async def run_integrity_monitor():
    """
    Background loop: periodically check whether previously-backed-up tables
    have unexpectedly gone empty (data loss), and auto-restore if so.
    """
    interval = cfg.integrity_check_interval_minutes * 60
    while True:
        await asyncio.sleep(interval)
        try:
            async with AsyncSessionLocal() as db:
                lost = await _tables_with_expected_data_are_empty(db)
            if lost:
                log.warning("Data loss detected — restoring from latest dump")
                await broadcast_system_event(
                    "DATA_LOSS_DETECTED",
                    "Data loss detected — restoring from the latest backup...",
                )
                await restore_latest_dump()
        except Exception as e:
            log.error("Integrity check failed", error=str(e))
