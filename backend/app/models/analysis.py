# app/models/analysis.py
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Integer, DateTime, Text, JSON, ForeignKey, BigInteger
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_type: Mapped[str] = mapped_column(String(32))
    # object_detection | change_detection | video_analysis | telemetry_report
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    # queued | running | done | failed | cancelled
    mission_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    drone_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    submitted_by: Mapped[int] = mapped_column(Integer)   # user.id
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class JobArtifact(Base):
    """
    A file (source imagery, generated report, video) associated with an
    AnalysisJob and stored in MinIO. A job can have any number of artifacts,
    e.g. multiple source images plus a generated PDF report.
    """
    __tablename__ = "job_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("analysis_jobs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    # image | video | report_pdf
    object_key: Mapped[str] = mapped_column(String(512))
    # MinIO object key, e.g. jobs/{job_id}/{uuid}_{filename}
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    uploaded_by: Mapped[int] = mapped_column(Integer)   # user.id
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
