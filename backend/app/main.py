import asyncio
import sys
import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from app.core.audit_middleware import audit_mutations

from app.config import get_settings
from app.database import engine, ts_engine, Base, AsyncSessionLocal
from app.models.telemetry import TSBase
from app.core.events import init_rabbitmq, close_rabbitmq
from app.core.search import bulk_index_all, close_client as close_es
from app.core.auth import ensure_default_admin
from app.core.hf_feed import HFFeedListener, parse_allowed_sources
from app.core.backup import (
    run_backup_scheduler, run_integrity_monitor, restore_all,
    MAIN_TARGET, TELEMETRY_TARGET,
)

# Module routers
from app.core.system_events import router as system_events_router
from app.core.backup_router import router as backup_router
from app.modules.drone_control.router import router as control_router
from app.modules.drone_master.router import router as master_router
from app.modules.drone_inventory.router import router as inventory_router
from app.modules.drone_flight.router import router as flight_router
try:
    from app.modules.drone_analyst.router import router as analyst_router
except ModuleNotFoundError as exc:
    if exc.name != "app.modules.drone_analyst":
        raise
    analyst_router = None

# Auth router
from app.core.auth import router as auth_router, ensure_default_admin
from app.modules.drone_control.data_recorder import data_recorder

# uvloop is Linux/macOS-only — used inside the Docker container. When the
# backend is run natively on Windows (e.g. for OpenCV webcam access, see
# backend/run_native.ps1), fall back to the default asyncio event loop.
if sys.platform != "win32":
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

cfg = get_settings()
log = structlog.get_logger()
hf_feed = HFFeedListener(
    cfg.redis_url, cfg.hf_feed_host, cfg.hf_feed_port,
    allowed_sources=parse_allowed_sources(cfg.hf_feed_allowed_sources_str),
    max_msgs_per_sec=cfg.hf_feed_max_msgs_per_sec,
    max_speed_ms=cfg.hf_feed_max_speed_ms,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    log.info("DroneArjuna starting up", version=cfg.app_version)

    # Retry DB connection — backend may start before postgres DNS is ready
    for attempt in range(1, 11):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            break
        except Exception as e:
            log.warning(f"DB not ready (attempt {attempt}/10) — retrying in 3s", error=str(e))
            await asyncio.sleep(3)
    else:
        log.error("Could not connect to database after 10 attempts — exiting")
        raise RuntimeError("Database unavailable")

    # Same retry loop for TimescaleDB — its latest-state tables (telemetry,
    # telemetry_gauges) must exist before we can restore into them below.
    # The append-only hypertables (telemetry_history, battery_snapshots) are
    # set up later by data_recorder.start(); that ordering doesn't matter
    # here since those tables are deliberately not backed up (see backup.py).
    for attempt in range(1, 11):
        try:
            async with ts_engine.begin() as conn:
                await conn.run_sync(TSBase.metadata.create_all)
            break
        except Exception as e:
            log.warning(f"TimescaleDB not ready (attempt {attempt}/10) — retrying in 3s", error=str(e))
            await asyncio.sleep(3)
    else:
        log.error("Could not connect to TimescaleDB after 10 attempts — exiting")
        raise RuntimeError("TimescaleDB unavailable")

    # If the Postgres or TimescaleDB volumes were wiped but a backup exists in
    # MinIO, restore now — before seeding a default admin into what would
    # otherwise look like a brand-new, empty database.
    await restore_all()

    # Seed default admin account if DB is empty
    async with AsyncSessionLocal() as db:
        await ensure_default_admin(db)

    async def initialize_secondary_services():
        """Start non-critical integrations without delaying API availability."""
        try:
            await init_rabbitmq()
            from app.modules.drone_control.mavlink_manager import mavlink_manager
            await mavlink_manager.start_geofence_rtl_consumer()
            if analyst_router is not None:
                from app.modules.drone_analyst.job_consumer import start_job_consumer
                await start_job_consumer()
            else:
                log.warning("Drone Analyst module is missing; analyst routes and jobs are disabled")
            from app.core.storage import ensure_bucket
            await ensure_bucket()
            await data_recorder.start()
            await hf_feed.start()
            async with AsyncSessionLocal() as db:
                await bulk_index_all(db)
            log.info("Secondary services initialised")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("Secondary service initialization failed", error=str(exc))

    _secondary_task = asyncio.create_task(
        initialize_secondary_services(), name="secondary-services"
    )
    from app.modules.drone_control.auto_connector import run_auto_connector
    _auto_connector_task = asyncio.create_task(run_auto_connector(AsyncSessionLocal), name="auto-connector")
    _backup_task = asyncio.create_task(run_backup_scheduler(MAIN_TARGET), name="backup-scheduler")
    _integrity_task = asyncio.create_task(run_integrity_monitor(MAIN_TARGET), name="integrity-monitor")
    _ts_backup_task = asyncio.create_task(run_backup_scheduler(TELEMETRY_TARGET), name="telemetry-backup-scheduler")
    _ts_integrity_task = asyncio.create_task(run_integrity_monitor(TELEMETRY_TARGET), name="telemetry-integrity-monitor")

    log.info("Primary services initialised — ready to accept connections")
    yield

    # Graceful shutdown
    _all_tasks = (
        _secondary_task, _auto_connector_task, _backup_task, _integrity_task,
        _ts_backup_task, _ts_integrity_task,
    )
    for task in _all_tasks:
        task.cancel()
    for task in _all_tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    log.info("DroneArjuna shutting down")
    await hf_feed.stop()
    await data_recorder.stop()
    await close_rabbitmq()
    await close_es()
    await engine.dispose()
    await ts_engine.dispose()


app = FastAPI(
    title=cfg.app_name,
    version=cfg.app_version,
    description="Military Drone Ground Control System — REST + WebSocket API",
    docs_url="/api/docs" if cfg.enable_api_docs else None,
    redoc_url="/api/redoc" if cfg.enable_api_docs else None,
    openapi_url="/api/openapi.json" if cfg.enable_api_docs else None,
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "no-referrer")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    h.setdefault("Content-Security-Policy",
                 "default-src 'none'; frame-ancestors 'none'" if not cfg.enable_api_docs
                 else "default-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net data:")
    h.setdefault("Cache-Control", "no-store")
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp
app.middleware("http")(audit_mutations)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ── Routers ───────────────────────────────────────────────────────
app.include_router(system_events_router, prefix="/api/system",  tags=["System"])
app.include_router(backup_router,        prefix="/api/system",  tags=["System"])
app.include_router(auth_router,      prefix="/api/auth",      tags=["Auth"])
app.include_router(control_router,   prefix="/api/drone-control", tags=["Drone Control"])
app.include_router(master_router,    prefix="/api/master",    tags=["Drone Master"])
app.include_router(inventory_router, prefix="/api/inventory", tags=["Drone Inventory"])
app.include_router(flight_router,    prefix="/api/flight",    tags=["Drone Flight"])
if analyst_router is not None:
    app.include_router(analyst_router, prefix="/api/analyst", tags=["Drone Analyst"])


@app.get("/api/health", tags=["System"])
async def health():
    return {"status": "ok", "version": cfg.app_version}
