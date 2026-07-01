from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


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


# ── Config Template Settings sub-models ──────────────────────────

class MavlinkParams(BaseModel):
    """ArduPilot parameter values stored in human units (m, m/s, degrees)."""
    wpnav_speed_ms:     Optional[float] = None   # WPNAV_SPEED
    wpnav_speed_up_ms:  Optional[float] = None   # WPNAV_SPEED_UP
    wpnav_speed_dn_ms:  Optional[float] = None   # WPNAV_SPEED_DN
    wpnav_accel_ms2:    Optional[float] = None   # WPNAV_ACCEL
    rtl_altitude_m:     Optional[float] = None   # RTL_ALTITUDE
    rtl_speed_ms:       Optional[float] = None   # RTL_SPEED
    land_speed_ms:      Optional[float] = None   # LAND_SPEED
    angle_max_deg:      Optional[float] = None   # ANGLE_MAX
    pilot_speed_up_ms:  Optional[float] = None   # PILOT_SPEED_UP
    arming_check_mask:  Optional[int]   = None   # ARMING_CHECK bitmask


class FailsafeSettings(BaseModel):
    battery_enable:    bool = True
    battery_voltage_v: Optional[float] = None
    battery_mah:       Optional[int]   = None
    battery_action:    Literal["RTL", "LAND", "HOLD", "CONTINUE"] = "RTL"
    gcs_enable:        bool = True
    gcs_action:        Literal["RTL", "LAND", "HOLD", "CONTINUE"] = "RTL"
    rc_enable:         bool = True
    rc_action:         Literal["RTL", "LAND", "HOLD"] = "RTL"
    ekf_action:        Literal["RTL", "LAND", "HOLD"] = "LAND"


class GeofenceDefaults(BaseModel):
    fence_type:    Literal["circle", "polygon", "altitude", "composite"] = "composite"
    radius_m:      Optional[float] = None
    alt_max_m:     Optional[float] = None
    alt_min_m:     float = 10.0
    breach_action: Literal["RTL", "LAND", "HOLD"] = "RTL"


class BatteryThresholds(BaseModel):
    capacity_mah:   Optional[int] = None
    low_pct:        int = 30
    rtl_pct:        int = 20
    land_pct:       int = 10
    min_to_arm_pct: int = 50

    @model_validator(mode="after")
    def rtl_above_land(self) -> "BatteryThresholds":
        if self.rtl_pct <= self.land_pct:
            raise ValueError(
                f"battery.rtl_pct ({self.rtl_pct}%) must be greater than "
                f"land_pct ({self.land_pct}%)"
            )
        return self


class PreflightChecks(BaseModel):
    required_gps_fix:     Literal["3D", "DGPS", "RTK"] = "3D"
    min_satellites:       int   = 6
    max_hdop:             float = 2.0
    min_voltage_to_arm_v: Optional[float] = None


class MissionConstraints(BaseModel):
    max_waypoints:            int   = 100
    min_waypoint_alt_m:       float = 10.0
    max_waypoint_alt_m:       Optional[float] = None
    default_cruise_speed_ms:  Optional[float] = None
    default_loiter_radius_m:  float = 20.0
    default_photo_interval_s: Optional[float] = None
    max_wind_speed_ms:        Optional[float] = None


class TelemetrySettings(BaseModel):
    telemetry_rate_hz:   int   = 4
    heartbeat_timeout_s: float = 5.0
    hf_message_filter:   list[str] = Field(default_factory=list)


class ConfigSettings(BaseModel):
    mavlink:   MavlinkParams      = Field(default_factory=MavlinkParams)
    failsafe:  FailsafeSettings   = Field(default_factory=FailsafeSettings)
    geofence:  GeofenceDefaults   = Field(default_factory=GeofenceDefaults)
    battery:   BatteryThresholds  = Field(default_factory=BatteryThresholds)
    preflight: PreflightChecks    = Field(default_factory=PreflightChecks)
    mission:   MissionConstraints = Field(default_factory=MissionConstraints)
    telemetry: TelemetrySettings  = Field(default_factory=TelemetrySettings)


# ── Config Templates ──────────────────────────────────────────────

class DroneConfigTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    drone_type_id: int
    settings: ConfigSettings = Field(default_factory=ConfigSettings)

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
    settings: Optional[ConfigSettings] = None


class DroneConfigTemplateOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    drone_type_id: int
    settings: dict   # raw pass-through — DB stores the serialized form
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


class GeofenceSetRequest(BaseModel):
    geofence: Optional[dict] = None   # GeoJSON Polygon/MultiPolygon; None clears the fence
