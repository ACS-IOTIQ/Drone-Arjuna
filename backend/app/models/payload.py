from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Float, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PayloadType(Base):
    """Catalogue of payload types (EO camera, LiDAR, jammer, etc.)."""
    __tablename__ = "payload_types"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    manufacturer: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # sensor | combat | comms | other
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="sensor")
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    voltage_v: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    max_current_a: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    has_gimbal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Sensor-specific (populated when category == 'sensor')
    sensor_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    frame_rate_fps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Combat-specific
    payload_function: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    effective_range_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
