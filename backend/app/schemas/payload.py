"""
Payload schemas — sensor and combat/action payloads.

Note: The Payload ORM model (models/payload.py) is a V2 deliverable
alongside the full Drone Master expansion. These schemas are defined
now so routers and frontend API contracts are stable.
"""
from typing import Optional, Literal
from pydantic import BaseModel, field_validator
from datetime import datetime


class PayloadTypeCreate(BaseModel):
    name: str
    manufacturer: str
    model: str
    category: Literal["sensor", "combat", "comms", "other"]

    # Physical
    weight_kg: float
    length_mm: Optional[float] = None
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None
    mounting_interface: Optional[str] = None    # e.g. "NATO STANAG 3910"

    # Power
    voltage_v: float
    max_current_a: float
    avg_current_a: Optional[float] = None

    # ── Sensor-specific (nullable for non-sensor payloads) ────────
    sensor_type: Optional[str] = None           # EO, IR, SAR, LIDAR, SIGINT, etc.
    resolution: Optional[str] = None            # e.g. "4K", "12MP"
    frame_rate_fps: Optional[float] = None
    spectral_bands: Optional[str] = None        # e.g. "visible, MWIR, LWIR"
    data_rate_mbps: Optional[float] = None
    has_gimbal: bool = False
    gimbal_axes: Optional[int] = None           # 2 or 3

    # ── Combat/action-specific ────────────────────────────────────
    payload_function: Optional[str] = None      # weapon, jammer, dispenser
    effective_range_m: Optional[float] = None
    munition_type: Optional[str] = None

    # Compatibility — list of drone_type IDs this payload can mount on
    compatible_drone_type_ids: list[int] = []

    notes: Optional[str] = None
    is_active: bool = True

    @field_validator("weight_kg")
    @classmethod
    def weight_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("weight_kg must be positive")
        return v


class PayloadTypeOut(PayloadTypeCreate):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PayloadTypeUpdate(BaseModel):
    name: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    category: Optional[str] = None
    weight_kg: Optional[float] = None
    voltage_v: Optional[float] = None
    max_current_a: Optional[float] = None
    sensor_type: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class CompatibilityCheckRequest(BaseModel):
    drone_type_id: int
    payload_type_id: int


class CompatibilityCheckResult(BaseModel):
    compatible: bool
    reason: Optional[str] = None       # populated when compatible is False
    weight_margin_kg: Optional[float] = None
    power_margin_w: Optional[float] = None