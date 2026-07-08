"""
Data Recorder — persists current drone telemetry to Postgres.

`telemetry` and `telemetry_gauges` each hold exactly one row per drone_id.
Every StateManager update UPSERTs (INSERT ... ON CONFLICT (drone_id) DO
UPDATE) that row immediately — no batching — so the DB always reflects the
same values the UI is showing, with no queue lag. No history is retained.
"""
import asyncio
import structlog
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.database import TSSessionLocal, ts_engine
from app.models.telemetry import TelemetryFrame, TelemetryGauge, TSBase

log = structlog.get_logger()


class DataRecorder:
    """
    Subscribes to StateManager updates and immediately upserts the
    latest telemetry for that drone into Postgres.
    """

    # Fields compared to detect actual change — excludes recorded_at / mission context
    _COMPARE_FIELDS = (
        "lat", "lon", "alt_msl", "alt_agl", "heading",
        "roll_deg", "pitch_deg", "yaw_deg",
        "vx", "vy", "vz", "airspeed_ms", "groundspeed_ms", "climb_rate_ms", "throttle_pct",
        "battery_voltage_v", "battery_current_a", "battery_remaining_pct",
        "gps_fix_type", "gps_satellites", "gps_hdop",
        "flight_mode", "is_armed", "system_status", "rssi", "cpu_load_pct",
    )

    def __init__(self):
        # Last written values per drone_id — used for change detection
        self._last: dict[int, tuple] = {}

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
        log.info("DataRecorder started")

    async def stop(self):
        self._last.clear()

    # ── Public API ────────────────────────────────────────────────

    async def record(self, drone_id: int, state: dict):
        """Called by StateManager on every telemetry update. Upserts immediately."""
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
        snapshot = tuple(frame.get(f) for f in self._COMPARE_FIELDS)
        if self._last.get(drone_id) == snapshot:
            return  # Nothing changed — skip write
        self._last[drone_id] = snapshot

        try:
            async with TSSessionLocal() as session:
                frame_stmt = pg_insert(TelemetryFrame).values(frame)
                frame_stmt = frame_stmt.on_conflict_do_update(
                    index_elements=["drone_id"],
                    set_={c.name: c for c in frame_stmt.excluded if c.name != "drone_id"},
                )
                await session.execute(frame_stmt)

                gauge_stmt = pg_insert(TelemetryGauge).values(self._gauge_from_frame(frame))
                gauge_stmt = gauge_stmt.on_conflict_do_update(
                    index_elements=["drone_id"],
                    set_={c.name: c for c in gauge_stmt.excluded if c.name != "drone_id"},
                )
                await session.execute(gauge_stmt)

                await session.commit()
        except Exception as e:
            log.error("Telemetry upsert failed", error=str(e), drone_id=drone_id)

    @staticmethod
    def _gauge_from_frame(frame: dict) -> dict:
        return {
            "recorded_at":    frame["recorded_at"],
            "drone_id":       frame["drone_id"],
            "battery_pct":    frame.get("battery_remaining_pct", -1),
            "altitude_m":     frame.get("alt_agl", 0.0),
            "ground_speed_ms": frame.get("groundspeed_ms", 0.0),
            "gps_satellites": frame.get("gps_satellites", 0),
            "rssi":           frame.get("rssi", 0),
            "cpu_load_pct":   frame.get("cpu_load_pct", 0.0),
        }

    async def _ensure_schema(self):
        """
        Ensures `telemetry` and `telemetry_gauges` exist as plain tables with
        one row per drone_id. Safe to call repeatedly.

        If a previous run left these as TimescaleDB hypertables (time-series
        history), this migrates them: collapses existing rows down to the
        latest row per drone_id, then rebuilds as regular PK(drone_id) tables.
        """
        async with ts_engine.begin() as conn:
            # Drop the old continuous aggregate / view if a previous version left one.
            await conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS telemetry_1min CASCADE"))
            await conn.execute(text("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_class
                        WHERE relname = 'telemetry_gauges' AND relkind = 'v'
                    ) THEN
                        DROP VIEW telemetry_gauges CASCADE;
                    END IF;
                END $$
            """))

            for table in ("telemetry", "telemetry_gauges"):
                is_hypertable = (await conn.execute(text(
                    "SELECT 1 FROM timescaledb_information.hypertables "
                    "WHERE hypertable_name = :t"
                ), {"t": table})).first()
                if is_hypertable:
                    log.info("Collapsing hypertable history to latest row per drone", table=table)
                    await conn.execute(text(f"""
                        CREATE TABLE {table}_latest AS
                        SELECT DISTINCT ON (drone_id) *
                        FROM {table}
                        ORDER BY drone_id, recorded_at DESC
                    """))
                    await conn.execute(text(f"DROP TABLE {table} CASCADE"))
                    await conn.execute(text(f"ALTER TABLE {table}_latest RENAME TO {table}"))
                    await conn.execute(text(
                        f"ALTER TABLE {table} ADD PRIMARY KEY (drone_id)"
                    ))

            # Create tables via ORM metadata if they don't exist yet (fresh install)
            await conn.run_sync(TSBase.metadata.create_all)

        log.info("Telemetry schema verified — single row per drone_id")


# Module-level singleton — imported by mavlink_manager
data_recorder = DataRecorder()
