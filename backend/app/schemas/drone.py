from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, field_validator


# ── Drone Types ───────────────────────────────────────────────────

class DroneTypeCreate(BaseModel):
    name: str
    manufacturer: str
    model: str
    size_class: Literal["micro", "small", "medium", "large", "extra-large"]
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

    @field_validator("cruise_speed_ms")
    @classmethod
    def cruise_below_max(cls, v: float, info) -> float:
        max_s = info.data.get("max_speed_ms")
        if max_s is not None and v > max_s:
            raise ValueError("cruise_speed_ms must not exceed max_speed_ms")
        return v

    @field_validator("max_payload_weight_kg")
    @classmethod
    def payload_below_mtow(cls, v: float, info) -> float:
        mtow = info.data.get("max_takeoff_weight_kg")
        if mtow is not None and v >= mtow:
            raise ValueError("max_payload_weight_kg must be less than max_takeoff_weight_kg")
        return v


class DroneTypeOut(DroneTypeCreate):
    id: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class DroneTypeUpdate(BaseModel):
    """Partial update — all fields optional."""
    name: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    size_class: Optional[str] = None
    mission_type: Optional[str] = None
    is_vtol: Optional[bool] = None
    max_speed_ms: Optional[float] = None
    cruise_speed_ms: Optional[float] = None
    max_altitude_m: Optional[float] = None
    endurance_h: Optional[float] = None
    range_km: Optional[float] = None
    max_takeoff_weight_kg: Optional[float] = None
    max_payload_weight_kg: Optional[float] = None
    autopilot_type: Optional[str] = None
    notes: Optional[str] = None


# ── Drone Instances ───────────────────────────────────────────────

class DroneInstanceCreate(BaseModel):
    call_sign: str
    drone_type_id: int
    serial_number: str
    mavlink_system_id: int = 1
    notes: Optional[str] = None

    @field_validator("call_sign")
    @classmethod
    def call_sign_upper(cls, v: str) -> str:
        return v.upper().strip()


class DroneInstanceOut(DroneInstanceCreate):
    id: int
    status: str
    last_seen: Optional[datetime]
    total_flight_hours: float

    model_config = {"from_attributes": True}


class DroneInstanceUpdate(BaseModel):
    call_sign: Optional[str] = None
    drone_type_id: Optional[int] = None
    serial_number: Optional[str] = None
    mavlink_system_id: Optional[int] = None
    status: Optional[str] = None
    notes: Optional[str] = None


# ── Config Templates ──────────────────────────────────────────────

class DroneConfigTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    drone_type_id: int
    settings: dict = {}

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Template name must not be blank")
        return v.strip()


class DroneConfigTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    drone_type_id: Optional[int] = None
    settings: Optional[dict] = None


class DroneConfigTemplateOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    drone_type_id: int
    settings: dict
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── MAVLink connection / command ──────────────────────────────────

class ConnectRequest(BaseModel):
    drone_instance_id: int
    transport: Literal["udp", "tcp", "serial", "hf_serial", "hf_tcp"]
    host: Optional[str] = None
    port: Optional[int] = None
    serial_port: Optional[str] = None
    baud_rate: int = 57600
    hf_modem_type: str = "generic"  # harris / codan / barrett / generic (HF transports only)


class AutoConnectRequest(BaseModel):
    drone_instance_id: int


class CommandRequest(BaseModel):
    drone_id: int
    command: Literal[
        "arm", "disarm", "set_mode", "rtl",
        "land", "takeoff", "emergency_stop"
    ]
    params: dict = {}


class ConnectionStatusOut(BaseModel):
    drone_id: int
    call_sign: str
    transport: str
    connected: bool
    link_quality: int


class SimStartRequest(BaseModel):
    mission_id: int
    drone_instance_id: Optional[int] = None   # override mission's assigned drone
    speed_multiplier: float = 1.0


class SimCommandRequest(BaseModel):
    action: str          # arm | disarm | takeoff | set_mode | rtl | land | emergency_stop
    params: dict = {}
