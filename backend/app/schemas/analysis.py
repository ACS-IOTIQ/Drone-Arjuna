# app/schemas/analysis.py
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class AnalysisJobOut(BaseModel):
    id: str
    job_type: str
    status: str
    mission_id: Optional[int]
    drone_id: Optional[int]
    model_id: Optional[str]
    params: dict
    submitted_by: int
    result: Optional[dict]
    error: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    model_config = {"from_attributes": True}


class JobArtifactOut(BaseModel):
    id: str
    job_id: str
    kind: str
    object_key: str
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by: int
    created_at: datetime
    model_config = {"from_attributes": True}
