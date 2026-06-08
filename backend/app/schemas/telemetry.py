from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class TelemetryFrameOut(BaseModel):
    """API response shape for a single persisted telemetry frame."""
    recorded_at: datetime
    drone_id: int

    lat: float
    lon: float
    alt_msl: float
    alt_agl: float
    heading: float

    roll_deg: float
    pitch_deg: float
    yaw_deg: float

    airspeed_ms: float
    groundspeed_ms: float
    climb_rate_ms: float
    throttle_pct: int

    battery_voltage_v: float
    battery_current_a: float
    battery_remaining_pct: int

    gps_fix_type: str
    gps_satellites: int
    gps_hdop: float

    flight_mode: str
    is_armed: bool
    rssi: int
    cpu_load_pct: float

    mission_id: Optional[int] = None
    current_waypoint: Optional[int] = None

    model_config = {"from_attributes": True}


class TelemetryQueryParams(BaseModel):
    """Parameters for querying historical telemetry."""
    drone_id: int
    from_dt: datetime
    to_dt: datetime
    downsample_seconds: Optional[int] = None   # None = full resolution
    limit: int = 5000


class TelemetryStats(BaseModel):
    """Aggregate stats over a telemetry window — used in Monitor workspace."""
    drone_id: int
    from_dt: datetime
    to_dt: datetime
    frame_count: int
    avg_altitude_m: float
    max_altitude_m: float
    avg_groundspeed_ms: float
    max_groundspeed_ms: float
    min_battery_pct: int
    total_distance_km: float
    flight_duration_min: float