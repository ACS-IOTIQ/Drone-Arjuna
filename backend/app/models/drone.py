from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Float, Integer, Boolean, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class DroneType(Base):
    """Drone Master — type registry."""
    __tablename__ = "drone_types"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    manufacturer: Mapped[str] = mapped_column(String(128))
    model: Mapped[str] = mapped_column(String(128))
    size_class: Mapped[str] = mapped_column(String(32))       # micro/small/medium/large
    mission_type: Mapped[str] = mapped_column(String(64))     # ISR/strike/logistics
    is_vtol: Mapped[bool] = mapped_column(Boolean, default=True)
    max_speed_ms: Mapped[float] = mapped_column(Float)
    cruise_speed_ms: Mapped[float] = mapped_column(Float)
    max_altitude_m: Mapped[float] = mapped_column(Float)
    endurance_h: Mapped[float] = mapped_column(Float)
    range_km: Mapped[float] = mapped_column(Float)
    max_takeoff_weight_kg: Mapped[float] = mapped_column(Float)
    max_payload_weight_kg: Mapped[float] = mapped_column(Float)
    autopilot_type: Mapped[str] = mapped_column(String(64))   # ArduPilot/PX4/custom
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class DroneInstance(Base):
    """A specific registered drone unit."""
    __tablename__ = "drone_instances"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    call_sign: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    drone_type_id: Mapped[int] = mapped_column(Integer)
    serial_number: Mapped[str] = mapped_column(String(128), unique=True)
    mavlink_system_id: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="offline")  # online/offline/maintenance
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    total_flight_hours: Mapped[float] = mapped_column(Float, default=0.0)
    home_vessel_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class DroneConfigTemplate(Base):
    """
    Reusable configuration template for a drone type.
    Stores MAVLink parameters, geofence bounds, failsafe settings, etc.
    as a JSON blob keyed to a specific DroneType so incompatible templates
    cannot be applied to the wrong airframe.
    """
    __tablename__ = "drone_config_templates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    drone_type_id: Mapped[int] = mapped_column(Integer, index=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
