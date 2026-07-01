from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Float, Integer, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ThreatSystem(Base):
    """Drone Inventory — threat system knowledge base entry."""
    __tablename__ = "threat_systems"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(16))          # UAV/RADAR/SAM/EW
    manufacturer: Mapped[str] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(64))
    max_range_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_altitude_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_speed_kmh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    radar_cross_section_m2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    countermeasures: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    classification: Mapped[str] = mapped_column(String(32), default="UNCLASSIFIED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
