from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field

_LEVELS = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


# ── Drone <-> Payload ────────────────────────────────────────────────

class DronePayloadLinkCreate(BaseModel):
    drone_type_id: int
    payload_type_id: int
    is_primary: bool = False
    max_qty: int = Field(1, ge=1)
    notes: Optional[str] = None


class DronePayloadLinkUpdate(BaseModel):
    is_primary: Optional[bool] = None
    max_qty: Optional[int] = Field(None, ge=1)
    notes: Optional[str] = None


class DronePayloadLinkOut(BaseModel):
    id: int
    drone_type_id: int
    payload_type_id: int
    is_primary: bool
    max_qty: int
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Drone <-> Threat ─────────────────────────────────────────────────

class DroneThreatLinkCreate(BaseModel):
    drone_type_id: int
    threat_system_id: int
    exposure_level: _LEVELS = "MEDIUM"
    notes: Optional[str] = None


class DroneThreatLinkUpdate(BaseModel):
    exposure_level: Optional[_LEVELS] = None
    notes: Optional[str] = None


class DroneThreatLinkOut(BaseModel):
    id: int
    drone_type_id: int
    threat_system_id: int
    exposure_level: str
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Payload <-> Threat ───────────────────────────────────────────────

class PayloadThreatLinkCreate(BaseModel):
    payload_type_id: int
    threat_system_id: int
    effectiveness: _LEVELS = "MEDIUM"
    notes: Optional[str] = None


class PayloadThreatLinkUpdate(BaseModel):
    effectiveness: Optional[_LEVELS] = None
    notes: Optional[str] = None


class PayloadThreatLinkOut(BaseModel):
    id: int
    payload_type_id: int
    threat_system_id: int
    effectiveness: str
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
