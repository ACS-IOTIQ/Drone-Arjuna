"""
Shared test fixtures for DroneArjuna auth and RBAC tests.

Design notes
------------
* Env vars are set at the very top — before any app import — so
  pydantic-settings picks them up instead of the production .env file.
* Tests run against an in-memory SQLite database (aiosqlite + StaticPool).
  The production PostgreSQL / RabbitMQ / TimescaleDB are never contacted.
* The FastAPI lifespan is replaced with a no-op so startup hooks that
  hit external services are skipped entirely.
* AuditLogger (which writes raw SQL to an audit_logs table) is mocked
  globally so we do not need that table in the test schema.
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

# ── MUST come first: set test env before any app module is imported ───────────
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://da:da@localhost/da_test")
os.environ.setdefault("TIMESCALE_URL", "postgresql+asyncpg://da:da@localhost/da_ts_test")
os.environ.setdefault(
    "SECRET_KEY",
    "da_test_secret_key_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",  # 64 chars
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")

# Clear any cached Settings so our env vars are read fresh
from app.config import get_settings  # noqa: E402 — must be after os.environ setup
get_settings.cache_clear()

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import AsyncClient, ASGITransport  # noqa: E402
from jose import jwt  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

# Import models so they register with Base.metadata before create_all
from app.database import Base, get_db  # noqa: E402
from app.models.user import User  # noqa: E402
import app.models.drone  # noqa: F401, E402 — registers DroneType, DroneInstance
import app.models.mission  # noqa: F401, E402 — registers Mission, Waypoint
import app.models.vessel  # noqa: F401, E402 — registers NavalVessel
import app.models.telemetry  # noqa: F401, E402 — registers telemetry models

cfg = get_settings()

# ── In-memory SQLite test engine ──────────────────────────────────────────────
# StaticPool: all AsyncSession objects share the same underlying SQLite
# connection, which is required for in-memory DBs (otherwise each new
# connection opens a blank database).
_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
_test_engine = create_async_engine(
    _TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = async_sessionmaker(_test_engine, expire_on_commit=False)


# ── Table lifecycle ───────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", autouse=True)
async def _create_tables():
    """Create ORM tables once per session, drop them on teardown."""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ── AuditLogger suppression ───────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _mock_audit_logger():
    """
    Replace AuditLogger with a no-op so auth routes don't try to INSERT into
    the audit_logs table (which is created by a raw-SQL migration, not ORM).
    """
    with patch("app.core.auth.AuditLogger") as mock_cls:
        inst = mock_cls.return_value
        inst.login_success = AsyncMock()
        inst.login_failed = AsyncMock()
        inst.user_created = AsyncMock()
        yield


# ── FastAPI test client ───────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    """
    HTTPX AsyncClient pointed at the FastAPI app with:
      - get_db overridden to use the SQLite test engine
      - lifespan replaced with a no-op (no real DB / Rabbit connections)
    """
    from app.main import app

    async def _override_get_db():
        async with _TestSession() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    app.dependency_overrides[get_db] = _override_get_db
    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _noop_lifespan

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    app.router.lifespan_context = original_lifespan


# ── User fixtures ─────────────────────────────────────────────────────────────
# Each fixture opens its own session (separate from the client's request
# session) so that committed rows are visible to subsequent request sessions.

@pytest_asyncio.fixture
async def admin_user():
    """An admin User persisted for the duration of a single test."""
    from app.core.auth import hash_password

    async with _TestSession() as session:
        user = User(
            username="admin_test",
            email="admin_test@da.local",
            hashed_password=hash_password("Admin@1234"),
            full_name="Test Admin",
            role="admin",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id

    yield user

    async with _TestSession() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        u = result.scalar_one_or_none()
        if u:
            await session.delete(u)
            await session.commit()


@pytest_asyncio.fixture
async def flight_controller_user():
    """A flight_controller User persisted for the duration of a single test."""
    from app.core.auth import hash_password

    async with _TestSession() as session:
        user = User(
            username="fc_test",
            email="fc_test@da.local",
            hashed_password=hash_password("FlightCtrl@99"),
            full_name="Test FC",
            role="flight_controller",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id

    yield user

    async with _TestSession() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        u = result.scalar_one_or_none()
        if u:
            await session.delete(u)
            await session.commit()


@pytest_asyncio.fixture
async def viewer_user():
    """A viewer User persisted for the duration of a single test."""
    from app.core.auth import hash_password

    async with _TestSession() as session:
        user = User(
            username="viewer_test",
            email="viewer_test@da.local",
            hashed_password=hash_password("Viewer@9999"),
            full_name="Test Viewer",
            role="viewer",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id

    yield user

    async with _TestSession() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        u = result.scalar_one_or_none()
        if u:
            await session.delete(u)
            await session.commit()


# ── Token factory fixtures ────────────────────────────────────────────────────

@pytest.fixture
def make_token():
    """Factory fixture: mints a valid JWT for the given user id + role."""
    def _inner(user_id: int, role: str, *, expire_minutes: int = 30) -> str:
        payload = {
            "sub": str(user_id),
            "role": role,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=expire_minutes),
        }
        return jwt.encode(payload, cfg.secret_key, algorithm=cfg.algorithm)

    return _inner


@pytest.fixture
def make_expired_token():
    """Factory fixture: mints a JWT whose exp is already in the past."""
    def _inner(user_id: int, role: str) -> str:
        payload = {
            "sub": str(user_id),
            "role": role,
            "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
        }
        return jwt.encode(payload, cfg.secret_key, algorithm=cfg.algorithm)

    return _inner
