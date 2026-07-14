from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field


_CATEGORIES = Literal["UAV", "RADAR", "SAM", "EW"]


class ThreatSystemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    category: _CATEGORIES
    manufacturer: str = Field(..., min_length=1, max_length=128)
    country: str = Field(..., min_length=1, max_length=64)
    max_range_km: Optional[float] = Field(None, ge=0)
    max_altitude_m: Optional[float] = Field(None, ge=0)
    max_speed_kmh: Optional[float] = Field(None, ge=0)
    radar_cross_section_m2: Optional[float] = Field(None, ge=0)
    countermeasures: list[str] = Field(default_factory=list)
    notes: Optional[str] = None
    classification: str = Field("UNCLASSIFIED", max_length=32)


class ThreatSystemUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    category: Optional[_CATEGORIES] = None
    manufacturer: Optional[str] = Field(None, min_length=1, max_length=128)
    country: Optional[str] = Field(None, min_length=1, max_length=64)
    max_range_km: Optional[float] = Field(None, ge=0)
    max_altitude_m: Optional[float] = Field(None, ge=0)
    max_speed_kmh: Optional[float] = Field(None, ge=0)
    radar_cross_section_m2: Optional[float] = Field(None, ge=0)
    countermeasures: Optional[list[str]] = None
    notes: Optional[str] = None
    classification: Optional[str] = Field(None, max_length=32)


class ThreatNotesPatch(BaseModel):
    notes: str = Field(..., min_length=0)


class ThreatSystemOut(BaseModel):
    id: int
    name: str
    category: str
    manufacturer: str
    country: str
    max_range_km: Optional[float] = None
    max_altitude_m: Optional[float] = None
    max_speed_kmh: Optional[float] = None
    radar_cross_section_m2: Optional[float] = None
    countermeasures: list[str]
    notes: Optional[str] = None
    classification: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
