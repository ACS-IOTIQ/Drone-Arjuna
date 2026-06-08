# ═══════════════════════════════════════════
# app/models/mission.py
# ═══════════════════════════════════════════
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Float, Integer, Boolean, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mission_type: Mapped[str] = mapped_column(String(64))  # ISR/strike/patrol/logistics
    status: Mapped[str] = mapped_column(String(32), default="planning")
    # planning | approved | executing | completed | aborted
    created_by: Mapped[int] = mapped_column(Integer)       # user.id
    drone_instance_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    geofence: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # GeoJSON polygon
    home_point_type: Mapped[str] = mapped_column(String(32), default="fixed")  # fixed | dynamic_vessel
    home_vessel_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Waypoint(Base):
    __tablename__ = "waypoints"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    mission_id: Mapped[int] = mapped_column(Integer, index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    altitude_m: Mapped[float] = mapped_column(Float)
    altitude_ref: Mapped[str] = mapped_column(String(8), default="AGL")  # AGL | MSL
    speed_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    heading_deg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    action: Mapped[str] = mapped_column(String(32), default="none")
    # none | loiter | photo | survey | payload_trigger
    loiter_time_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_home: Mapped[bool] = mapped_column(Boolean, default=False)


# ═══════════════════════════════════════════
# app/schemas/mission.py
# ═══════════════════════════════════════════
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class WaypointCreate(BaseModel):
    sequence: int
    latitude: float
    longitude: float
    altitude_m: float
    altitude_ref: str = "AGL"
    speed_ms: Optional[float] = None
    heading_deg: Optional[float] = None
    action: str = "none"
    loiter_time_s: Optional[float] = None
    is_home: bool = False


class WaypointOut(WaypointCreate):
    id: int
    mission_id: int
    model_config = {"from_attributes": True}


class MissionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    mission_type: str = "ISR"
    drone_instance_id: Optional[int] = None
    waypoints: list[WaypointCreate] = []
    geofence: Optional[dict] = None
    notes: Optional[str] = None


class MissionOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    mission_type: str
    status: str
    created_by: int
    drone_instance_id: Optional[int]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    waypoints: list[WaypointOut] = []
    model_config = {"from_attributes": True}


class MissionSummary(BaseModel):
    total_distance_km: float
    estimated_flight_time_min: float
    estimated_battery_pct: float
    waypoint_count: int