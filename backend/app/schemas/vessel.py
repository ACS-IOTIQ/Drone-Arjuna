from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class NavalVesselCreate(BaseModel):
    vessel_id: str = Field(..., description="Short unique identifier, e.g. INS-VIKRANT")
    name: str
    vessel_type: str = Field(..., description="frigate / corvette / OPV / patrol")
    hull_number: Optional[str] = None
    sea_state: int = Field(default=0, ge=0, le=9)
    deck_status: str = Field(default="clear", description="clear / occupied / restricted")
    landing_spots: int = Field(default=1, ge=1)
    hf_modem_type: Optional[str] = None
    hf_frequency_mhz: Optional[float] = None
    hf_link_encrypted: bool = True
    notes: Optional[str] = None


class NavalVesselUpdate(BaseModel):
    name: Optional[str] = None
    vessel_type: Optional[str] = None
    hull_number: Optional[str] = None
    sea_state: Optional[int] = Field(default=None, ge=0, le=9)
    deck_status: Optional[str] = None
    landing_spots: Optional[int] = None
    hf_modem_type: Optional[str] = None
    hf_frequency_mhz: Optional[float] = None
    hf_link_encrypted: Optional[bool] = None
    notes: Optional[str] = None


class VesselPositionUpdate(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    heading_deg: Optional[float] = Field(default=None, ge=0.0, lt=360.0)
    speed_kts: Optional[float] = None


class NavalVesselOut(NavalVesselCreate):
    id: int
    latitude: Optional[float]
    longitude: Optional[float]
    heading_deg: Optional[float]
    speed_kts: Optional[float]
    position_updated_at: Optional[datetime]
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}
