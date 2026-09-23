from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

cfg = get_settings()

# ── Main relational DB (PostgreSQL + PostGIS) ─────────────────────
engine = create_async_engine(
    cfg.database_url,
    pool_size=20,
    max_overflow=40,
    pool_pre_ping=True,
    echo=cfg.debug,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ── Telemetry time-series DB (TimescaleDB) ───────────────────────
ts_engine = create_async_engine(
    cfg.timescale_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

TSSessionLocal = async_sessionmaker(
    ts_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


# Dependency injected into FastAPI routes
async def get_db() -> AsyncSession:
    # Debounced check so data loss (e.g. a wiped table/dump deleted from
    # MinIO) is caught within seconds of the next API request, instead of
    # waiting for the periodic integrity monitor's interval. Imported lazily
    # to avoid a circular import (app.core.backup imports from this module).
    # Fire-and-forget — runs in the background so this request doesn't wait
    # on a separate DB session + MinIO round-trip before getting its own.
    from app.core.backup import maybe_check_and_restore
    maybe_check_and_restore()
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_ts_db() -> AsyncSession:
    from app.core.backup import maybe_check_and_restore_telemetry
    maybe_check_and_restore_telemetry()
    async with TSSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise