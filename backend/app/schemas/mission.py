from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, field_validator, model_validator


# ── Waypoints ─────────────────────────────────────────────────────

class WaypointCreate(BaseModel):
    sequence: int
    latitude: float
    longitude: float
    altitude_m: float
    altitude_ref: Literal["AGL", "MSL"] = "AGL"
    speed_ms: Optional[float] = None
    heading_deg: Optional[float] = None
    action: Literal[
        "none", "loiter", "photo", "survey",
        "payload_trigger", "rtl", "land"
    ] = "none"
    loiter_time_s: Optional[float] = None
    is_home: bool = False

    @field_validator("latitude")
    @classmethod
    def lat_range(cls, v: float) -> float:
        if not (-90 <= v <= 90):
            raise ValueError("latitude must be between -90 and 90")
        return v

    @field_validator("longitude")
    @classmethod
    def lon_range(cls, v: float) -> float:
        if not (-180 <= v <= 180):
            raise ValueError("longitude must be between -180 and 180")
        return v

    @field_validator("altitude_m")
    @classmethod
    def alt_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("altitude_m must be >= 0")
        return v

    @model_validator(mode="after")
    def loiter_requires_time(self) -> "WaypointCreate":
        if self.action == "loiter" and not self.loiter_time_s:
            raise ValueError("loiter_time_s is required when action is 'loiter'")
        return self


class WaypointOut(WaypointCreate):
    id: int
    mission_id: int

    model_config = {"from_attributes": True}


class WaypointUpdate(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[float] = None
    altitude_ref: Optional[str] = None
    speed_ms: Optional[float] = None
    heading_deg: Optional[float] = None
    action: Optional[str] = None
    loiter_time_s: Optional[float] = None
    sequence: Optional[int] = None


# ── Missions ──────────────────────────────────────────────────────

class MissionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    mission_type: str = "ISR"
    drone_instance_id: Optional[int] = None
    waypoints: list[WaypointCreate] = []
    geofence: Optional[dict] = None        # GeoJSON Polygon
    payload_weight_kg: Optional[float] = None
    notes: Optional[str] = None

    @field_validator("payload_weight_kg")
    @classmethod
    def payload_weight_non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("payload_weight_kg must be >= 0")
        return v

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Mission name must not be blank")
        return v.strip()

    @field_validator("waypoints")
    @classmethod
    def sequences_must_be_unique(cls, v: list) -> list:
        seqs = [wp.sequence for wp in v]
        if len(seqs) != len(set(seqs)):
            raise ValueError("Waypoint sequence numbers must be unique within a mission")
        return v


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
    geofence: Optional[dict] = None
    payload_weight_kg: Optional[float] = None

    model_config = {"from_attributes": True}


class MissionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    mission_type: Optional[str] = None
    drone_instance_id: Optional[int] = None
    notes: Optional[str] = None
    geofence: Optional[dict] = None
    payload_weight_kg: Optional[float] = None


class MissionStatusUpdate(BaseModel):
    status: Literal[
        "planning", "approved", "executing", "completed", "aborted"
    ]


class MissionSummary(BaseModel):
    """Computed flight estimates returned by /missions/{id}/summary."""
    total_distance_km: float
    estimated_flight_time_min: float
    estimated_battery_pct: float
    waypoint_count: int