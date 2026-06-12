from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Float, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PayloadType(Base):
    """Catalogue of payload categories (EO camera, LiDAR, jammer, etc.)."""
    __tablename__ = "payload_types"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Payload(Base):
    """A specific physical payload unit registered in the inventory."""
    __tablename__ = "payloads"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payload_types.id"), nullable=False, index=True
    )
    # Nullable — payload may be in storage and not mounted on any drone
    drone_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("drone_instances.id"), nullable=True, index=True
    )
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    # available | mounted | maintenance | decommissioned
    status: Mapped[str] = mapped_column(String(32), default="available")
    manufacturer: Mapped[str] = mapped_column(String(128), nullable=False)
    serial_number: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
