from typing import Optional
from pydantic import BaseModel, field_validator
from datetime import datetime


# ── Compatibility (kept for existing __init__.py contract) ────────────────────

class CompatibilityCheckRequest(BaseModel):
    drone_type_id: int
    payload_type_id: int


class CompatibilityCheckResult(BaseModel):
    compatible: bool
    reason: Optional[str] = None
    weight_margin_kg: Optional[float] = None
    power_margin_w: Optional[float] = None


# ── Payload Type ──────────────────────────────────────────────────────────────

class PayloadTypeCreate(BaseModel):
    name: str
    description: Optional[str] = None


class PayloadTypeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class PayloadTypeOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Payload ───────────────────────────────────────────────────────────────────

class PayloadCreate(BaseModel):
    name: str
    payload_type_id: int
    drone_id: Optional[int] = None     # None when in storage, not mounted
    weight: float                       # kg
    status: str = "available"          # available | mounted | maintenance | decommissioned
    manufacturer: str
    serial_number: str

    @field_validator("weight")
    @classmethod
    def weight_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("weight must be positive")
        return v

    @field_validator("status")
    @classmethod
    def status_valid(cls, v: str) -> str:
        allowed = {"available", "mounted", "maintenance", "decommissioned"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v


class PayloadUpdate(BaseModel):
    name: Optional[str] = None
    drone_id: Optional[int] = None
    weight: Optional[float] = None
    status: Optional[str] = None
    manufacturer: Optional[str] = None


class PayloadOut(BaseModel):
    id: int
    name: str
    payload_type_id: int
    drone_id: Optional[int]
    weight: float
    status: str
    manufacturer: str
    serial_number: str
    created_at: datetime

    model_config = {"from_attributes": True}
