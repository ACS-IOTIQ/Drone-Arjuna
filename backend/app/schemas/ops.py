"""
Typed request bodies for endpoints that used to accept a raw ``dict``
(unvalidated types, no bounds, extra keys silently ignored).
Unknown fields are rejected so typos and smuggled keys fail loudly.
"""
import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MAX_PARAMS_BYTES = 20_000
_MAX_SURVEY_CELLS = 250_000          # (area / spacing^2) cap — bounds CPU and response size
_METRES_PER_DEG = 111_320.0


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DroneStatusUpdate(_Strict):
    status: Literal["online", "offline", "maintenance", "mission"]


class PayloadAssign(_Strict):
    """payload_type_id = null clears the payload."""
    payload_type_id: Optional[int] = Field(None, ge=1)


class AnalysisJobCreate(_Strict):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())   # "model_id" is a real API field

    job_type: Literal["object_detection", "change_detection",
                      "video_analysis", "telemetry_report"] = "telemetry_report"
    mission_id: Optional[int] = Field(None, ge=1)
    drone_id: Optional[int] = Field(None, ge=1)
    model_id: Optional[str] = Field(None, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("params")
    @classmethod
    def _params_bounded(cls, v: dict) -> dict:
        if len(json.dumps(v, default=str)) > _MAX_PARAMS_BYTES:
            raise ValueError(f"params too large (max {_MAX_PARAMS_BYTES} bytes)")
        return v


class SurveyGridRequest(_Strict):
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=500,
                                               description="[[lat, lon], ...]")
    altitude_m: float = Field(gt=0, le=5000)
    spacing_m: float = Field(50.0, ge=1, le=5000)
    speed_ms: Optional[float] = Field(None, gt=0, le=100)

    @field_validator("polygon")
    @classmethod
    def _valid_coordinates(cls, pts: list) -> list:
        for lat, lon in pts:
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("polygon points must be [lat, lon] within valid ranges")
        return pts

    @model_validator(mode="after")
    def _bounded_area(self):
        lats = [p[0] for p in self.polygon]
        lons = [p[1] for p in self.polygon]
        height = (max(lats) - min(lats)) * _METRES_PER_DEG
        width = (max(lons) - min(lons)) * _METRES_PER_DEG
        if (height * width) / (self.spacing_m ** 2) > _MAX_SURVEY_CELLS:
            raise ValueError("survey area too large for this spacing; increase spacing_m "
                             "or split the polygon")
        return self
