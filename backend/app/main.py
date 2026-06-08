import uvloop
import asyncio
import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import get_settings
from app.database import engine, ts_engine, Base, AsyncSessionLocal
from app.core.events import init_rabbitmq, close_rabbitmq
from app.core.auth import ensure_default_admin

# Module routers
from app.modules.drone_control.router import router as control_router
from app.modules.drone_master.router import router as master_router
from app.modules.drone_inventory.router import router as inventory_router
from app.modules.drone_flight.router import router as flight_router
from app.modules.drone_analyst.router import router as analyst_router

# Auth router
from app.core.auth import router as auth_router, ensure_default_admin
from app.modules.drone_control.data_recorder import data_recorder

# Use uvloop for faster async I/O
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

cfg = get_settings()
log = structlog.get_logger()


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

    # Connect to RabbitMQ event bus
    await init_rabbitmq()

    # Start telemetry recorder (creates TimescaleDB hypertable if needed)
    await data_recorder.start()

    # Seed default admin account if DB is empty
    async with AsyncSessionLocal() as db:
        await ensure_default_admin(db)

    log.info("All services initialised — ready to accept connections")
    yield

    # Graceful shutdown
    log.info("DroneArjuna shutting down")
    await data_recorder.stop()
    await close_rabbitmq()
    await engine.dispose()
    await ts_engine.dispose()


app = FastAPI(
    title=cfg.app_name,
    version=cfg.app_version,
    description="Military Drone Ground Control System — REST + WebSocket API",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ── Routers ───────────────────────────────────────────────────────
app.include_router(auth_router,      prefix="/api/auth",      tags=["Auth"])
app.include_router(control_router,   prefix="/api/drone-control", tags=["Drone Control"])
app.include_router(master_router,    prefix="/api/master",    tags=["Drone Master"])
app.include_router(inventory_router, prefix="/api/inventory", tags=["Drone Inventory"])
app.include_router(flight_router,    prefix="/api/flight",    tags=["Drone Flight"])
app.include_router(analyst_router,   prefix="/api/analyst",   tags=["Drone Analyst"])


@app.get("/api/health", tags=["System"])
async def health():
    return {"status": "ok", "version": cfg.app_version}