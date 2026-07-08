"""
Telemetry models for TimescaleDB hypertables.

These models live on the TIMESCALE database (ts_engine / TSSessionLocal),
NOT the main PostgreSQL database. They are NOT included in Base.metadata
to avoid Alembic accidentally running them against the wrong engine.

The hypertable is created via raw SQL in the lifespan startup
(see app/modules/drone_control/data_recorder.py).
"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    BigInteger, Integer, Float, String,
    Boolean, DateTime, Text
)
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase


class TSBase(DeclarativeBase):
    """Separate base for TimescaleDB models — keeps them out of main Alembic."""
    pass


class TelemetryFrame(TSBase):
    """
    Current-state telemetry table — one row per drone_id, updated in place
    on every change (UPSERT in data_recorder.py). No history is retained;
    `recorded_at` reflects the timestamp of the last update, not a log entry.
    """
    __tablename__ = "telemetry"

    drone_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Position ──────────────────────────────────────────────────
    lat: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    lon: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    alt_msl: Mapped[float] = mapped_column(Float, default=0.0)   # metres MSL
    alt_agl: Mapped[float] = mapped_column(Float, default=0.0)   # metres AGL
    heading: Mapped[float] = mapped_column(Float, default=0.0)   # degrees 0-360

    # ── Attitude ─────────────────────────────────────────────────
    roll_deg: Mapped[float] = mapped_column(Float, default=0.0)
    pitch_deg: Mapped[float] = mapped_column(Float, default=0.0)
    yaw_deg: Mapped[float] = mapped_column(Float, default=0.0)

    # ── Velocity ─────────────────────────────────────────────────
    vx: Mapped[float] = mapped_column(Float, default=0.0)        # m/s north
    vy: Mapped[float] = mapped_column(Float, default=0.0)        # m/s east
    vz: Mapped[float] = mapped_column(Float, default=0.0)        # m/s down
    airspeed_ms: Mapped[float] = mapped_column(Float, default=0.0)
    groundspeed_ms: Mapped[float] = mapped_column(Float, default=0.0)
    climb_rate_ms: Mapped[float] = mapped_column(Float, default=0.0)
    throttle_pct: Mapped[int] = mapped_column(Integer, default=0)

    # ── Battery / Power ──────────────────────────────────────────
    battery_voltage_v: Mapped[float] = mapped_column(Float, default=0.0)
    battery_current_a: Mapped[float] = mapped_column(Float, default=0.0)
    battery_remaining_pct: Mapped[int] = mapped_column(Integer, default=-1)

    # ── GPS ──────────────────────────────────────────────────────
    gps_fix_type: Mapped[str] = mapped_column(String(16), default="No GPS")
    gps_satellites: Mapped[int] = mapped_column(Integer, default=0)
    gps_hdop: Mapped[float] = mapped_column(Float, default=99.9)

    # ── System ───────────────────────────────────────────────────
    flight_mode: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    is_armed: Mapped[bool] = mapped_column(Boolean, default=False)
    system_status: Mapped[int] = mapped_column(Integer, default=0)
    rssi: Mapped[int] = mapped_column(Integer, default=0)
    cpu_load_pct: Mapped[float] = mapped_column(Float, default=0.0)

    # ── Mission context (optional, populated when executing) ─────
    mission_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_waypoint: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class TelemetryGauge(TSBase):
    """
    Dashboard gauge table — Battery, Altitude, GND Speed, GPS Sats, RSSI, CPU Load.
    One row per drone_id, updated in place (UPSERT) whenever a gauge value changes
    (change-detection in DataRecorder.record()). No history is retained.
    """
    __tablename__ = "telemetry_gauges"

    drone_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    battery_pct: Mapped[int] = mapped_column(Integer, default=-1)
    altitude_m: Mapped[float] = mapped_column(Float, default=0.0)
    ground_speed_ms: Mapped[float] = mapped_column(Float, default=0.0)
    gps_satellites: Mapped[int] = mapped_column(Integer, default=0)
    rssi: Mapped[int] = mapped_column(Integer, default=0)
    cpu_load_pct: Mapped[float] = mapped_column(Float, default=0.0)


class SystemMetric(TSBase):
    """
    GCS-side system health metrics hypertable.
    Records backend process stats — CPU, memory, queue depths.
    Useful for diagnosing GCS performance issues under load.
    """
    __tablename__ = "system_metrics"

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        primary_key=True,
    )
    service: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. "drone_control"

    cpu_pct: Mapped[float] = mapped_column(Float, default=0.0)
    mem_mb: Mapped[float] = mapped_column(Float, default=0.0)
    active_connections: Mapped[int] = mapped_column(Integer, default=0)
    mq_queue_depth: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
