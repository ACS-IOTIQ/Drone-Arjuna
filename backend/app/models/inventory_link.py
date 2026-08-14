from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class DronePayloadLink(Base):
    """Which payload types a drone type is rated to carry."""
    __tablename__ = "drone_payload_links"
    __table_args__ = (
        UniqueConstraint("drone_type_id", "payload_type_id", name="uq_drone_payload_link"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    drone_type_id: Mapped[int] = mapped_column(
        ForeignKey("drone_types.id", ondelete="CASCADE"), index=True
    )
    payload_type_id: Mapped[int] = mapped_column(
        ForeignKey("payload_types.id", ondelete="CASCADE"), index=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    max_qty: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class DroneThreatLink(Base):
    """Exposure of a drone type to a threat system."""
    __tablename__ = "drone_threat_links"
    __table_args__ = (
        UniqueConstraint("drone_type_id", "threat_system_id", name="uq_drone_threat_link"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    drone_type_id: Mapped[int] = mapped_column(
        ForeignKey("drone_types.id", ondelete="CASCADE"), index=True
    )
    threat_system_id: Mapped[int] = mapped_column(
        ForeignKey("threat_systems.id", ondelete="CASCADE"), index=True
    )
    exposure_level: Mapped[str] = mapped_column(String(16), default="MEDIUM")  # LOW/MEDIUM/HIGH/CRITICAL
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class PayloadThreatLink(Base):
    """Effectiveness of a payload type against a threat system."""
    __tablename__ = "payload_threat_links"
    __table_args__ = (
        UniqueConstraint("payload_type_id", "threat_system_id", name="uq_payload_threat_link"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    payload_type_id: Mapped[int] = mapped_column(
        ForeignKey("payload_types.id", ondelete="CASCADE"), index=True
    )
    threat_system_id: Mapped[int] = mapped_column(
        ForeignKey("threat_systems.id", ondelete="CASCADE"), index=True
    )
    effectiveness: Mapped[str] = mapped_column(String(16), default="MEDIUM")  # LOW/MEDIUM/HIGH/CRITICAL
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
