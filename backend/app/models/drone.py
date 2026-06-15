# ═══════════════════════════════════════════
# app/models/drone.py
# ═══════════════════════════════════════════
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


class DroneConfigTemplate(Base):
    """Saved MAVLink parameter set for a drone type."""
    __tablename__ = "drone_config_templates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    drone_type_id: Mapped[int] = mapped_column(Integer)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


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


# ═══════════════════════════════════════════
# app/schemas/drone.py
# ═══════════════════════════════════════════
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class DroneTypeCreate(BaseModel):
    name: str
    manufacturer: str
    model: str
    size_class: str
    mission_type: str
    is_vtol: bool = True
    max_speed_ms: float
    cruise_speed_ms: float
    max_altitude_m: float
    endurance_h: float
    range_km: float
    max_takeoff_weight_kg: float
    max_payload_weight_kg: float
    autopilot_type: str
    notes: Optional[str] = None


class DroneTypeOut(DroneTypeCreate):
    id: int
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class DroneInstanceCreate(BaseModel):
    call_sign: str
    drone_type_id: int
    serial_number: str
    mavlink_system_id: int = 1
    notes: Optional[str] = None


class DroneInstanceOut(DroneInstanceCreate):
    id: int
    status: str
    last_seen: Optional[datetime]
    total_flight_hours: float
    model_config = {"from_attributes": True}


class ConnectRequest(BaseModel):
    drone_instance_id: int
    transport: str        # "udp" | "tcp" | "serial"
    host: Optional[str] = None
    port: Optional[int] = None
    serial_port: Optional[str] = None
    baud_rate: int = 57600


class CommandRequest(BaseModel):
    drone_id: int
    command: str          # "arm" | "disarm" | "set_mode" | "rtl" | "land" | "takeoff"
    params: dict = {}