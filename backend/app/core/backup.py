"""
Database backup / auto-restore.

Periodically dumps every table under `Base.metadata` (the main PostgreSQL
database — missions, drones, users, etc.) to timestamped JSON files, and
periodically checks whether tables that should have data are empty. If
they are, the most recent dump is restored automatically.

The TimescaleDB telemetry database is covered the same way, but only for
its "latest state" tables (`telemetry`, `telemetry_gauges`) — the
append-only history tables (`telemetry_history`, `battery_snapshots`) are
high-frequency and already time-bounded by their own retention policy, so
backing them up would mean re-dumping a fast-growing table on every cycle
for data that expires anyway; a lost replay window isn't worth that cost.

Deliberately implemented with plain SQLAlchemy row dumps instead of shelling
out to `pg_dump`/`psql` (those binaries aren't in the backend image, and this
keeps the whole thing async and dependency-free).

Dumps are written to local disk (fast, simple restore path) and then
uploaded to a MinIO bucket (durable, survives the backend container/volume
being wiped). Restore prefers the newest object in MinIO and falls back to
the newest local file if MinIO is unreachable.
"""
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
import structlog
from sqlalchemy import Date, DateTime, MetaData, event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, AsyncSessionLocal, engine, TSSessionLocal, ts_engine
from app.core.system_events import broadcast_system_event
from app.models.telemetry import TSBase, TelemetryFrame, TelemetryGauge
import app.models  # noqa: F401 — registers every table on Base.metadata before we dump it

log = structlog.get_logger()
cfg = get_settings()

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent

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


RESTORE_HISTORY_DEPTH = 10


@dataclass
class DumpTarget:
    """Everything backup/restore needs for one database (main or telemetry)."""

    name: str
    metadata: MetaData
    session_factory: async_sessionmaker
    backup_dir: Path
    minio_bucket: str

    def sorted_tables(self):
        return self.metadata.sorted_tables


MAIN_TARGET = DumpTarget(
    name="main",
    metadata=Base.metadata,
    session_factory=AsyncSessionLocal,
    backup_dir=_BACKEND_ROOT / "backups",
    minio_bucket="db-backups",
)

# Telemetry only backs up latest-state tables (see module docstring) — build
# a standalone MetaData containing just those two tables' definitions so
# `sorted_tables()` doesn't pull in the history hypertables.
_TS_LATEST_STATE_METADATA = MetaData()
TelemetryFrame.__table__.tometadata(_TS_LATEST_STATE_METADATA)
TelemetryGauge.__table__.tometadata(_TS_LATEST_STATE_METADATA)

TELEMETRY_TARGET = DumpTarget(
    name="telemetry",
    metadata=_TS_LATEST_STATE_METADATA,
    session_factory=TSSessionLocal,
    backup_dir=_BACKEND_ROOT / "backups_telemetry",
    minio_bucket="db-backups-telemetry",
)

ALL_TARGETS = (MAIN_TARGET, TELEMETRY_TARGET)


def _ensure_bucket(client, bucket: str):
    try:
        client.head_bucket(Bucket=bucket)
    except (BotoCoreError, ClientError):
        client.create_bucket(Bucket=bucket)


async def _reset_id_sequences(db, target: DumpTarget, restored_tables: set[str]):
    """Advance integer id sequences after inserting explicit backup ids."""
    for table in target.sorted_tables():
        if table.name not in restored_tables:
            continue
        if "id" not in table.columns:
            continue
        sequence = await db.scalar(
            text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
            {"table_name": table.name},
        )
        if not sequence:
            continue
        table_name = table.name.replace('"', '""')
        await db.execute(text(
            f'SELECT setval(:sequence_name, COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) '
            f'FROM "{table_name}"'
        ), {"sequence_name": sequence})


async def create_dump(target: DumpTarget = MAIN_TARGET, tables: set[str] | None = None) -> Path:
    """
    Dump table rows to a single timestamped JSON file, then upload it to MinIO.

    When `tables` is given, only those tables are re-read from the database —
    everything else is carried over unchanged from the previous dump. This
    keeps a write-triggered dump (one commit touching one table) from paying
    the cost of a full-database SELECT + serialize on every debounce window;
    the periodic scheduler still calls this with `tables=None` for a full
    dump, which also self-heals anything the incremental path might have
    missed (e.g. after a restart with no previous dump to carry forward).
    """
    target.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dump_name = f"dump_{stamp}.json"
    dump_path = target.backup_dir / dump_name

    base_data: dict = {}
    tables_to_read = {table.name for table in target.sorted_tables()}
    if tables is not None:
        previous = _latest_dump(target)
        if previous is not None:
            base_data = json.loads(previous.read_text())
            tables_to_read = tables

    data = dict(base_data)
    async with target.session_factory() as db:
        for table in target.sorted_tables():
            if table.name not in tables_to_read:
                continue
            result = await db.execute(select(table))
            rows = [dict(row._mapping) for row in result.fetchall()]
            data[table.name] = rows

    dump_path.write_text(json.dumps(data, default=_json_default, indent=2))
    log.info(
        "Database dump created", db=target.name, path=str(dump_path),
        tables=len(data), tables_read=len(tables_to_read),
    )

    _upload_to_minio(target, dump_path, dump_name)
    _rotate_old_dumps(target)
    return dump_path


def _upload_to_minio(target: DumpTarget, dump_path: Path, dump_name: str):
    try:
        client = _minio_client()
        _ensure_bucket(client, target.minio_bucket)
        client.upload_file(str(dump_path), target.minio_bucket, dump_name)
        log.info("Database dump uploaded to MinIO", db=target.name, bucket=target.minio_bucket, key=dump_name)
    except (BotoCoreError, ClientError) as e:
        log.error("Failed to upload dump to MinIO", db=target.name, error=str(e))


def _rotate_old_dumps(target: DumpTarget):
    dumps = sorted(target.backup_dir.glob("dump_*.json"))
    excess = len(dumps) - cfg.backup_retention_count
    for stale in dumps[:excess]:
        stale.unlink(missing_ok=True)
        log.info("Rotated old dump", db=target.name, path=str(stale))

    _rotate_old_minio_dumps(target)


def _rotate_old_minio_dumps(target: DumpTarget):
    try:
        client = _minio_client()
        _ensure_bucket(client, target.minio_bucket)
        keys = sorted(
            obj["Key"] for obj in client.list_objects_v2(Bucket=target.minio_bucket).get("Contents", [])
        )
        excess = len(keys) - cfg.backup_retention_count
        for stale_key in keys[:excess]:
            client.delete_object(Bucket=target.minio_bucket, Key=stale_key)
            log.info("Rotated old dump from MinIO", db=target.name, key=stale_key)
    except (BotoCoreError, ClientError) as e:
        log.error("Failed to rotate dumps in MinIO", db=target.name, error=str(e))


def _recent_dump_keys_from_minio(target: DumpTarget, limit: int) -> list[str]:
    """Newest-first list of up to `limit` dump keys in MinIO."""
    try:
        client = _minio_client()
        _ensure_bucket(client, target.minio_bucket)
        keys = sorted(
            obj["Key"] for obj in client.list_objects_v2(Bucket=target.minio_bucket).get("Contents", [])
        )
        return list(reversed(keys))[:limit]
    except (BotoCoreError, ClientError) as e:
        log.error("Failed to list dumps in MinIO", db=target.name, error=str(e))
        return []


def _latest_dump(target: DumpTarget) -> Path | None:
    dumps = sorted(target.backup_dir.glob("dump_*.json"))
    return dumps[-1] if dumps else None


def _recent_local_dumps(target: DumpTarget, limit: int) -> list[Path]:
    """Newest-first list of up to `limit` local dump files."""
    return list(reversed(sorted(target.backup_dir.glob("dump_*.json"))))[:limit]


def _fetch_recent_dumps(target: DumpTarget, limit: int) -> list[tuple[Path, str]]:
    """
    Resolve up to `limit` newest dumps, newest first, preferring MinIO
    (durable) over local disk. A dump immediately after partial data loss
    only has empty arrays for the lost tables, so callers that need to
    restore a specific table must be able to look further back than just
    the single latest dump to find one that still has that table's rows.
    """
    target.backup_dir.mkdir(parents=True, exist_ok=True)
    results: list[tuple[Path, str]] = []

    minio_keys = _recent_dump_keys_from_minio(target, limit)
    if minio_keys:
        client = _minio_client()
        for minio_key in minio_keys:
            local_path = target.backup_dir / minio_key
            if not local_path.exists():
                try:
                    client.download_file(target.minio_bucket, minio_key, str(local_path))
                    log.info("Downloaded dump from MinIO", db=target.name, key=minio_key)
                except (BotoCoreError, ClientError) as e:
                    log.error("Failed to download dump from MinIO", db=target.name, key=minio_key, error=str(e))
                    continue
            results.append((local_path, minio_key))
        if results:
            return results

    return [(p, p.name) for p in _recent_local_dumps(target, limit)]


async def restore_latest_dump(target: DumpTarget = MAIN_TARGET) -> bool:
    """
    Restore every currently-empty table, using the newest available dump that
    still has rows for that table. A single dump taken right after partial
    data loss (e.g. one table truncated) only has empty arrays for the lost
    table, so the latest dump alone isn't enough — this walks back through
    recent dumps (newest first) per table until it finds one with data.
    """
    fetched = await asyncio.to_thread(_fetch_recent_dumps, target, RESTORE_HISTORY_DEPTH)
    if not fetched:
        log.warning("Restore requested but no dump exists in MinIO or on disk", db=target.name)
        await broadcast_system_event(
            "BACKUP_MISSING",
            f"Data loss was detected in the {target.name} database, but no backup dump is "
            "available in MinIO or on disk to restore from.",
        )
        return False

    dumps = await asyncio.to_thread(
        lambda: [(name, json.loads(path.read_text())) for path, name in fetched]
    )

    restored_tables: set[str] = set()
    restored_from: set[str] = set()
    async with target.session_factory() as db:
        for table in target.sorted_tables():
            count = (await db.execute(
                text(f'SELECT COUNT(*) FROM "{table.name}"')
            )).scalar_one()
            if count > 0:
                continue
            for dump_name, data in dumps:
                rows = data.get(table.name) or []
                if not rows:
                    continue
                await db.execute(table.insert(), _restore_rows(table, rows))
                log.info(
                    "Restored table from dump", db=target.name, table=table.name,
                    rows=len(rows), dump_file=dump_name,
                )
                restored_tables.add(table.name)
                restored_from.add(dump_name)
                break
        await _reset_id_sequences(db, target, restored_tables)
        await db.commit()

    if not restored_tables:
        log.info("Restore check found nothing to restore", db=target.name)
        return False

    log.info("Database restore complete", db=target.name, tables=sorted(restored_tables))
    await broadcast_system_event(
        "DATA_RESTORED",
        f"Data loss was detected in the {target.name} database and it was automatically "
        "restored from the latest backup.",
        db=target.name,
        dump_file=", ".join(sorted(restored_from)),
    )
    return True


async def restore_all() -> None:
    """Run restore for every backed-up database (main + telemetry)."""
    for target in ALL_TARGETS:
        await restore_latest_dump(target)


async def _tables_with_expected_data_are_empty(db, target: DumpTarget) -> bool:
    """
    True if ANY table that some recent dump has rows for is currently empty
    in the database — i.e. that table's data was lost, whether or not other
    tables are still intact, and even if the single latest dump no longer has
    rows for it (a dump taken right after the loss only has empty arrays for
    the lost table). Restoring is per-table safe (restore_latest_dump only
    inserts into tables that are currently empty), so detection must also be
    per-table rather than requiring the whole database to be wiped, and must
    look back across recent dump history rather than just the newest one.
    """
    fetched = _fetch_recent_dumps(target, RESTORE_HISTORY_DEPTH)
    if not fetched:
        return False

    tables_with_known_data: set[str] = set()
    for path, _name in fetched:
        data = json.loads(path.read_text())
        for table_name, rows in data.items():
            if rows:
                tables_with_known_data.add(table_name)

    for table_name in tables_with_known_data:
        count = (await db.execute(
            text(f'SELECT COUNT(*) FROM "{table_name}"')
        )).scalar_one()
        if count == 0:
            return True
    return False


async def check_and_restore_if_lost(target: DumpTarget = MAIN_TARGET) -> bool:
    """Run one integrity check and restore immediately if data loss is found."""
    try:
        async with target.session_factory() as db:
            lost = await _tables_with_expected_data_are_empty(db, target)
        if lost:
            log.warning("Data loss detected — restoring from latest dump", db=target.name)
            await broadcast_system_event(
                "DATA_LOSS_DETECTED",
                f"Data loss detected in the {target.name} database — restoring from the "
                "latest backup...",
                db=target.name,
            )
            await restore_latest_dump(target)
            return True
    except Exception as e:
        log.error("Integrity check failed", db=target.name, error=str(e))
    return False


async def run_backup_scheduler(target: DumpTarget = MAIN_TARGET):
    """Background loop: dump the database on a fixed interval."""
    interval = cfg.backup_interval_minutes * 60
    while True:
        try:
            await create_dump(target)
        except Exception as e:
            log.error("Scheduled backup failed", db=target.name, error=str(e))
        await asyncio.sleep(interval)


async def run_integrity_monitor(target: DumpTarget = MAIN_TARGET):
    """
    Background loop: periodically check whether previously-backed-up tables
    have unexpectedly gone empty (data loss), and auto-restore if so.

    This is a slow-interval safety net — the fast path is
    `maybe_check_and_restore()`, called from every request's DB dependency,
    which catches data loss within seconds instead of waiting up to
    `integrity_check_interval_minutes`.
    """
    interval = cfg.integrity_check_interval_minutes * 60
    while True:
        await asyncio.sleep(interval)
        await check_and_restore_if_lost(target)


_last_request_check: float = 0.0
_REQUEST_CHECK_DEBOUNCE_SECONDS = 5.0
_request_check_lock = asyncio.Lock()


def maybe_check_and_restore():
    """
    Debounced integrity check triggered from the request path (see
    `app.dependencies.get_db`). Ensures data loss is detected and restored
    within seconds of happening, rather than only on the periodic monitor's
    interval, without running the check on every single request.

    Fires the actual check as a background task rather than being awaited
    inline — check_and_restore_if_lost() opens its own DB session, lists/
    reads from MinIO, and potentially inserts rows, none of which the
    request that happened to trigger it should have to wait on before it
    can get its own DB session and proceed.
    """
    global _last_request_check
    loop = asyncio.get_event_loop()
    now = loop.time()
    if now - _last_request_check < _REQUEST_CHECK_DEBOUNCE_SECONDS:
        return
    if _request_check_lock.locked():
        return
    _last_request_check = now

    async def _run():
        async with _request_check_lock:
            await check_and_restore_if_lost(MAIN_TARGET)

    asyncio.ensure_future(_run())


_last_ts_request_check: float = 0.0
_ts_request_check_lock = asyncio.Lock()


def maybe_check_and_restore_telemetry():
    """Telemetry-database counterpart of `maybe_check_and_restore()` above,
    triggered from `app.database.get_ts_db`."""
    global _last_ts_request_check
    loop = asyncio.get_event_loop()
    now = loop.time()
    if now - _last_ts_request_check < _REQUEST_CHECK_DEBOUNCE_SECONDS:
        return
    if _ts_request_check_lock.locked():
        return
    _last_ts_request_check = now

    async def _run():
        async with _ts_request_check_lock:
            await check_and_restore_if_lost(TELEMETRY_TARGET)

    asyncio.ensure_future(_run())


# ── Write-triggered backup ─────────────────────────────────────────
# Any commit that changed rows schedules a debounced dump shortly after,
# so a UI create/update/delete is durably in MinIO within seconds instead
# of waiting for the next hourly `run_backup_scheduler` tick. Only the
# tables actually touched by commits in the debounce window are re-read —
# under sustained writes this avoids re-scanning every table in the
# database on every 3s window (see create_dump's `tables` param).
#
# Deliberately main-DB only — telemetry writes at high frequency and is
# covered by its own slower periodic scheduler (see run_backup_scheduler
# wiring in main.py) instead of a write-triggered debounce, which would
# otherwise spam MinIO on every telemetry update.

_WRITE_DUMP_DEBOUNCE_SECONDS = 3.0
_write_dump_handle: asyncio.TimerHandle | None = None
_write_dump_lock = asyncio.Lock()
_pending_dirty_tables: set[str] = set()


async def _debounced_write_dump():
    global _pending_dirty_tables
    async with _write_dump_lock:
        tables, _pending_dirty_tables = _pending_dirty_tables, set()
        if not tables:
            return
        try:
            await create_dump(MAIN_TARGET, tables=tables)
        except Exception as e:
            log.error("Write-triggered backup failed", error=str(e))


def _schedule_write_dump(dirty_tables: set[str]):
    global _write_dump_handle
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return
    _pending_dirty_tables.update(dirty_tables)
    if _write_dump_handle is not None:
        _write_dump_handle.cancel()
    _write_dump_handle = loop.call_later(
        _WRITE_DUMP_DEBOUNCE_SECONDS,
        lambda: asyncio.ensure_future(_debounced_write_dump()),
    )


def _is_main_db_session(session) -> bool:
    """Only trigger write-backups for the main relational DB, not TimescaleDB
    (high-frequency telemetry writes would otherwise spam MinIO dumps)."""
    try:
        return session.get_bind() is engine.sync_engine
    except Exception:
        return False


@event.listens_for(Session, "before_commit")
def _on_before_commit(session):
    if not _is_main_db_session(session):
        return
    changed = list(session.new) + list(session.dirty) + list(session.deleted)
    session.info["_da_dirty_tables"] = {
        obj.__table__.name for obj in changed if hasattr(obj, "__table__")
    }


@event.listens_for(Session, "after_commit")
def _on_after_commit(session):
    dirty_tables = session.info.pop("_da_dirty_tables", None)
    if dirty_tables:
        _schedule_write_dump(dirty_tables)
