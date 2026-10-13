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
import enum
import asyncio
import sys
import types
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

if not hasattr(enum, "StrEnum"):
    class StrEnum(str, enum.Enum):
        pass

    enum.StrEnum = StrEnum

if "uvloop" not in sys.modules:
    uvloop_stub = types.ModuleType("uvloop")
    uvloop_stub.EventLoopPolicy = asyncio.DefaultEventLoopPolicy
    sys.modules["uvloop"] = uvloop_stub

# ── MUST come first: set test env before any app module is imported ───────────
os.environ["DEBUG"] = "false"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://da:da@localhost/da_test"
os.environ["TIMESCALE_URL"] = "postgresql+asyncpg://da:da@localhost/da_ts_test"
os.environ["SECRET_KEY"] = (
    "da_test_secret_key_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)
os.environ["MINIO_USER"] = "test_minio_user"
os.environ["MINIO_PASSWORD"] = "test_minio_password_x9"
os.environ["REDIS_URL"] = "redis://localhost:6379"
os.environ["AUDIT_MUTATIONS"] = "false"   # no Postgres in tests; middleware is tested with record_mutation patched
os.environ["RABBITMQ_URL"] = "amqp://guest:guest@localhost:5672/"
# Never let tests reach the real SMTP server configured in .env (Gmail) —
# approval/reject flows fire send_approval_email() as a background task via
# asyncio.create_task, and a real SMTP connection attempt outlives the test's
# event loop, producing "Task was destroyed but it is pending!" errors.
os.environ["SMTP_ENABLED"] = "false"

# Clear any cached Settings so our env vars are read fresh
from app.config import get_settings  # noqa: E402 — must be after os.environ setup
get_settings.cache_clear()

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import AsyncClient, ASGITransport  # noqa: E402
import jwt  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

# Import models so they register with Base.metadata before create_all
from app.database import Base, get_db as _db_get_db  # noqa: E402
from app.dependencies import get_db as _deps_get_db  # noqa: E402
from app.models.user import User  # noqa: E402
import app.models.drone  # noqa: F401, E402 — registers DroneType, DroneInstance
import app.models.mission  # noqa: F401, E402 — registers Mission, Waypoint
import app.models.vessel  # noqa: F401, E402 — registers NavalVessel
import app.models.telemetry  # noqa: F401, E402 — registers telemetry models
import app.models.payload  # noqa: F401, E402 — registers PayloadType
import app.models.threat   # noqa: F401, E402 — registers ThreatSystem
import app.models.analysis # noqa: F401, E402 — registers AnalysisJob, JobArtifact

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


@pytest_asyncio.fixture(autouse=True)
async def _truncate_tables():
    """
    Hard-delete all rows from every ORM table before each test.

    Because _create_tables is session-scoped the schema persists across
    the whole test run.  Soft-deleted rows (is_active=False) still occupy
    unique-constrained columns, so a later test that tries to create the
    same name would hit a DB-level IntegrityError.  Truncating before each
    test prevents that and makes every test start from a known-clean state.
    """
    # reversed(sorted_tables) removes children before parents
    ordered = list(reversed(Base.metadata.sorted_tables))
    async with _TestSession() as session:
        for table in ordered:
            await session.execute(text(f"DELETE FROM {table.name}"))
        await session.commit()
    yield


@pytest_asyncio.fixture(autouse=True)
async def _reset_mavlink_state():
    """
    mavlink_manager._connections and mission_simulator._flights are
    process-wide singletons keyed by drone_id. _truncate_tables resets the
    DB but NOT these in-memory dicts — since SQLite reuses low integer IDs
    after a table is emptied, a connection/simulation left over from one
    test (e.g. a started-but-not-stopped simulation) can silently attach
    itself to an unrelated drone in a later test that happens to reuse the
    same id. Clear both before and after every test to prevent that.
    """
    from app.modules.drone_control.mavlink_manager import mavlink_manager
    from app.modules.drone_control.mission_simulator import mission_simulator

    async def _clear():
        for did in list(mission_simulator._flights.keys()):
            await mission_simulator.stop(did)
        mavlink_manager._connections.clear()

    await _clear()
    yield
    await _clear()


# ── TimescaleDB suppression ───────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _no_sql_dump_fallback(monkeypatch, tmp_path):
    """Keep tests off the real database_dumps/ folder (mounted at /project in Docker)."""
    monkeypatch.setattr(get_settings(), "backup_sql_dump_dir", str(tmp_path / "no_sql_dumps"))


@pytest.fixture(autouse=True)
def _mock_ts_session():
    """
    Replace TSSessionLocal in the analyst service with a null async context
    manager that returns zero rows without ever touching asyncpg.

    Without this, each test gets a fresh event loop (function-scoped asyncio
    mode), but ts_engine's asyncpg pool was created in the app's startup loop.
    When asyncpg tries to reuse the stale connection it raises
    "Future attached to a different loop", then the pool cleanup raises
    "RuntimeError: Event loop is closed" — producing noisy ERROR log lines.

    The null mock makes every TS query return count=0 / empty series,
    which is correct for a test environment with no telemetry data.
    """
    from unittest.mock import AsyncMock, MagicMock

    class _NullResult:
        def scalar_one(self):
            return 0
        def mappings(self):
            m = MagicMock()
            m.all.return_value = []
            m.one.return_value = {}
            return m

    class _NullTSSession:
        async def __aenter__(self):
            sess = AsyncMock()
            sess.execute = AsyncMock(return_value=_NullResult())
            return sess
        async def __aexit__(self, *args):
            pass

    def _null_factory():
        return _NullTSSession()

    import app.modules.drone_analyst.service as _svc
    original = _svc.TSSessionLocal
    _svc.TSSessionLocal = _null_factory
    yield
    _svc.TSSessionLocal = original


# ── AuditLogger suppression ───────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _mock_audit_logger():
    """
    Replace AuditLogger with a no-op so auth routes don't try to INSERT into
    the audit_logs table (which is created by a raw-SQL migration, not ORM).
    """
    with patch("app.core.auth.AuditLogger") as mock_cls,          patch("app.modules.drone_control.router.AuditLogger") as router_cls:
        router_cls.return_value.command_sent = AsyncMock()
        inst = mock_cls.return_value
        inst.login_success = AsyncMock()
        inst.login_failed = AsyncMock()
        inst.user_created = AsyncMock()
        inst.user_password_changed = AsyncMock()
        inst.log = AsyncMock()
        inst.logout = AsyncMock()
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
    from app.dependencies import get_db as dependencies_get_db

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

    app.dependency_overrides[_db_get_db] = _override_get_db
    app.dependency_overrides[_deps_get_db] = _override_get_db
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
            email="admin_test@example.com",
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
async def mission_commander_user():
    """A mission_commander User persisted for the duration of a single test."""
    from app.core.auth import hash_password

    async with _TestSession() as session:
        user = User(
            username="mc_test",
            email="mc_test@example.com",
            hashed_password=hash_password("MissionCmd@99"),
            full_name="Test MC",
            role="mission_commander",
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
            email="fc_test@example.com",
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
            email="viewer_test@example.com",
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


@pytest_asyncio.fixture
async def intelligence_analyst_user():
    """An intelligence_analyst User persisted for the duration of a single test."""
    from app.core.auth import hash_password

    async with _TestSession() as session:
        user = User(
            username="ia_test",
            email="ia_test@example.com",
            hashed_password=hash_password("Analyst@9999"),
            full_name="Test Analyst",
            role="intelligence_analyst",
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
            "type": "access", "jti": __import__("uuid").uuid4().hex,
            "iat": int(datetime.now(timezone.utc).timestamp()),
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
            "type": "access", "jti": __import__("uuid").uuid4().hex,
            "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
        }
        return jwt.encode(payload, cfg.secret_key, algorithm=cfg.algorithm)

    return _inner


# ── In-memory Redis fake (no real Redis needed; keeps auth tests fast) ────────

class _FakeRedis:
    def __init__(self):
        self.d = {}

    async def get(self, k): return self.d.get(k)
    async def getdel(self, k): return self.d.pop(k, None)
    async def setex(self, k, ttl, v): self.d[k] = str(v)
    async def exists(self, k): return 1 if k in self.d else 0
    async def incr(self, k):
        self.d[k] = str(int(self.d.get(k, 0)) + 1)
        return int(self.d[k])
    async def expire(self, k, ttl): return True
    async def ttl(self, k): return 60
    async def delete(self, k): self.d.pop(k, None)

    def pipeline(self):
        outer = self

        class _P:
            def zremrangebyscore(self, *a): pass
            def zcard(self, *a): pass
            def zadd(self, *a): pass
            def expire(self, *a): pass
            async def execute(self): return [0, 0, 1, True]
        return _P()


@pytest.fixture(autouse=True)
def _fake_redis():
    fake = _FakeRedis()
    with patch("app.core.security.get_redis", return_value=fake), \
         patch("app.core.auth.get_redis", return_value=fake):
        yield fake


# ── Capture the emailed temporary password (never returned by the API) ───────

LAST_EMAILED = {}


@pytest.fixture(autouse=True)
def _capture_temp_password():
    async def _noop():
        return None

    def _fake(**kw):
        LAST_EMAILED["temp_password"] = kw.get("temp_password")
        return _noop()

    with patch("app.core.auth.send_approval_email", _fake):
        yield LAST_EMAILED
