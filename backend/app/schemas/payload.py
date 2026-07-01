from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel


# ── PayloadType ────────────────────────────────────────────────────────────────

class PayloadTypeCreate(BaseModel):
    name: str
    manufacturer: str
    model: str
    category: Literal["sensor", "combat", "comms", "other"] = "sensor"
    weight_kg: float = 0.0
    voltage_v: float = 5.0
    max_current_a: float = 2.0
    has_gimbal: bool = False
    sensor_type: Optional[str] = None
    resolution: Optional[str] = None
    frame_rate_fps: Optional[float] = None
    payload_function: Optional[str] = None
    effective_range_m: Optional[float] = None
    notes: Optional[str] = None


class PayloadTypeUpdate(BaseModel):
    name: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    category: Optional[Literal["sensor", "combat", "comms", "other"]] = None
    weight_kg: Optional[float] = None
    voltage_v: Optional[float] = None
    max_current_a: Optional[float] = None
    has_gimbal: Optional[bool] = None
    sensor_type: Optional[str] = None
    resolution: Optional[str] = None
    frame_rate_fps: Optional[float] = None
    payload_function: Optional[str] = None
    effective_range_m: Optional[float] = None
    notes: Optional[str] = None


class PayloadTypeOut(BaseModel):
    id: int
    name: str
    manufacturer: str
    model: str
    category: str
    weight_kg: float
    voltage_v: float
    max_current_a: float
    has_gimbal: bool
    sensor_type: Optional[str] = None
    resolution: Optional[str] = None
    frame_rate_fps: Optional[float] = None
    payload_function: Optional[str] = None
    effective_range_m: Optional[float] = None
    notes: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

