from typing import Optional
from datetime import datetime
from pydantic import BaseModel


# ── PayloadType ────────────────────────────────────────────────────────────────

class PayloadTypeCreate(BaseModel):
    name: str
    description: Optional[str] = None


class PayloadTypeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class PayloadTypeOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Payload ────────────────────────────────────────────────────────────────────

class PayloadCreate(BaseModel):
    name: str
    payload_type_id: int
    drone_id: Optional[int] = None
    weight: float
    status: str = "available"
    manufacturer: str
    serial_number: str


class PayloadUpdate(BaseModel):
    name: Optional[str] = None
    payload_type_id: Optional[int] = None
    drone_id: Optional[int] = None
    weight: Optional[float] = None
    status: Optional[str] = None
    manufacturer: Optional[str] = None
    serial_number: Optional[str] = None


class PayloadOut(BaseModel):
    id: int
    name: str
    payload_type_id: int
    drone_id: Optional[int] = None
    weight: float
    status: str
    manufacturer: str
    serial_number: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Compatibility (kept for schemas/__init__.py exports) ──────────────────────

class CompatibilityCheckRequest(BaseModel):
    drone_type_id: int
    payload_type_id: int


class CompatibilityCheckResult(BaseModel):
    compatible: bool
    reason: Optional[str] = None
    weight_margin_kg: Optional[float] = None
    power_margin_w: Optional[float] = None
