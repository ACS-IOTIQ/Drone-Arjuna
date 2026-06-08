"""
Data Recorder — persists telemetry frames to TimescaleDB.

Deliberately kept OFF the hot path:
  MAVLink → StateManager → WebSocket broadcast  (hot, sync, <5ms)
                         → DataRecorder         (warm, batched, async)

Frames are buffered in an asyncio.Queue and flushed in batches every
FLUSH_INTERVAL_S seconds. This keeps the database write completely
decoupled from the real-time telemetry pipeline.

Also handles:
  - TimescaleDB hypertable creation on first run
  - Retention policy setup (30-day full resolution)
  - Continuous aggregate (1-minute downsampled view) creation
"""
import asyncio
import structlog
from datetime import datetime, timezone
from sqlalchemy import text
from app.database import TSSessionLocal, ts_engine
from app.models.telemetry import TelemetryFrame, TSBase

log = structlog.get_logger()

FLUSH_INTERVAL_S = 2        # Batch flush every 2 seconds
BATCH_SIZE       = 500      # Max frames per flush
RETENTION_DAYS   = 30       # Full-resolution retention


class DataRecorder:
    """
    Subscribes to StateManager updates and persists telemetry
    to TimescaleDB via batched async inserts.
    """

    def __init__(self):
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=10_000)
        self._task: asyncio.Task | None = None

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self):
        """Call once during app startup (after DB is ready)."""
        for attempt in range(1, 11):
            try:
                await self._ensure_schema()
                break
            except Exception as e:
                log.warning(f"TimescaleDB not ready (attempt {attempt}/10) — retrying in 3s",
                            error=str(e))
                await asyncio.sleep(3)
        else:
            raise RuntimeError("TimescaleDB unavailable after 10 attempts")
        self._task = asyncio.create_task(self._flush_loop(), name="telemetry-recorder")
        log.info("DataRecorder started")

    async def stop(self):
        if self._task:
            self._task.cancel()
            # Flush remaining frames before shutdown
            await self._flush()

    # ── Public API ────────────────────────────────────────────────

    async def record(self, drone_id: int, state: dict):
        """
        Called by StateManager on every telemetry update.
        Non-blocking — drops the frame if the queue is full (back-pressure).
        """
        frame = {
            "recorded_at": datetime.now(timezone.utc),
            "drone_id": drone_id,
            "lat":              state.get("lat", 0.0),
            "lon":              state.get("lon", 0.0),
            "alt_msl":          state.get("alt_msl", 0.0),
            "alt_agl":          state.get("alt_agl", 0.0),
            "heading":          state.get("heading", 0.0),
            "roll_deg":         state.get("roll_deg", 0.0),
            "pitch_deg":        state.get("pitch_deg", 0.0),
            "yaw_deg":          state.get("yaw_deg", 0.0),
            "vx":               state.get("vx", 0.0),
            "vy":               state.get("vy", 0.0),
            "vz":               state.get("vz", 0.0),
            "airspeed_ms":      state.get("airspeed_ms", 0.0),
            "groundspeed_ms":   state.get("groundspeed_ms", 0.0),
            "climb_rate_ms":    state.get("climb_rate_ms", 0.0),
            "throttle_pct":     state.get("throttle_pct", 0),
            "battery_voltage_v":    state.get("battery_voltage_v", 0.0),
            "battery_current_a":    state.get("battery_current_a", 0.0),
            "battery_remaining_pct": state.get("battery_remaining_pct", -1),
            "gps_fix_type":     state.get("gps_fix_type", "No GPS"),
            "gps_satellites":   state.get("gps_satellites", 0),
            "gps_hdop":         state.get("gps_hdop", 99.9),
            "flight_mode":      state.get("flight_mode", "UNKNOWN"),
            "is_armed":         state.get("is_armed", False),
            "system_status":    state.get("system_status", 0),
            "rssi":             state.get("rssi", 0),
            "cpu_load_pct":     state.get("cpu_load_pct", 0.0),
            "mission_id":       state.get("mission_id"),
            "current_waypoint": state.get("current_waypoint"),
        }
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            log.warning("Telemetry recorder queue full — frame dropped", drone_id=drone_id)

    # ── Internal ─────────────────────────────────────────────────

    async def _flush_loop(self):
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_S)
            await self._flush()

    async def _flush(self):
        if self._queue.empty():
            return
        batch = []
        while not self._queue.empty() and len(batch) < BATCH_SIZE:
            batch.append(self._queue.get_nowait())
        if not batch:
            return
        try:
            async with TSSessionLocal() as session:
                session.add_all([TelemetryFrame(**f) for f in batch])
                await session.commit()
            log.debug("Telemetry flushed", count=len(batch))
        except Exception as e:
            log.error("Telemetry flush failed", error=str(e), batch_size=len(batch))

    async def _ensure_schema(self):
        """
        Creates the TimescaleDB hypertable and policies on first run.
        Safe to call repeatedly — all statements use IF NOT EXISTS.
        """
        async with ts_engine.begin() as conn:
            # Create the telemetry table
            await conn.run_sync(TSBase.metadata.create_all)

            # Convert to hypertable (no-op if already done)
            await conn.execute(text("""
                SELECT create_hypertable(
                    'telemetry', 'recorded_at',
                    if_not_exists => TRUE,
                    migrate_data  => TRUE
                )
            """))

            # Retention policy: drop chunks older than 30 days
            await conn.execute(text(f"""
                SELECT add_retention_policy(
                    'telemetry',
                    INTERVAL '{RETENTION_DAYS} days',
                    if_not_exists => TRUE
                )
            """))

            # Continuous aggregate: 1-minute downsampled view
            # Used by Monitor workspace for long-duration charts
            await conn.execute(text("""
                CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_1min
                WITH (timescaledb.continuous) AS
                SELECT
                    time_bucket('1 minute', recorded_at) AS bucket,
                    drone_id,
                    AVG(lat)               AS avg_lat,
                    AVG(lon)               AS avg_lon,
                    AVG(alt_agl)           AS avg_alt_agl,
                    MAX(alt_agl)           AS max_alt_agl,
                    AVG(groundspeed_ms)    AS avg_speed,
                    MAX(groundspeed_ms)    AS max_speed,
                    MIN(battery_remaining_pct) AS min_battery,
                    AVG(cpu_load_pct)      AS avg_cpu,
                    COUNT(*)               AS frame_count
                FROM telemetry
                GROUP BY bucket, drone_id
                WITH NO DATA
            """))

            # Refresh policy for the continuous aggregate
            await conn.execute(text("""
                SELECT add_continuous_aggregate_policy(
                    'telemetry_1min',
                    start_offset  => INTERVAL '2 hours',
                    end_offset    => INTERVAL '1 minute',
                    schedule_interval => INTERVAL '1 minute',
                    if_not_exists => TRUE
                )
            """))

        log.info("TimescaleDB schema verified", retention_days=RETENTION_DAYS)


# Module-level singleton — imported by mavlink_manager
data_recorder = DataRecorder()