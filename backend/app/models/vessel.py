from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Float, Integer, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class NavalVessel(Base):
    """
    A naval vessel that acts as a floating home base for ship-borne drone operations.
    Drones assigned to a vessel use dynamic return-to-ship instead of a fixed RTH point.
    Vessel position is updated in near-real-time via the HF link position feed.
    """
    __tablename__ = "naval_vessels"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    vessel_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # e.g. "INS-VIKRANT"
    name: Mapped[str] = mapped_column(String(128))
    vessel_type: Mapped[str] = mapped_column(String(64))       # frigate/corvette/OPV/patrol
    hull_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # Real-time position — updated by vessel_position_feed background task
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    heading_deg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    speed_kts: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    position_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Deck and operational state
    sea_state: Mapped[int] = mapped_column(Integer, default=0)        # Beaufort 0-9
    deck_status: Mapped[str] = mapped_column(String(32), default="clear")  # clear/occupied/restricted
    landing_spots: Mapped[int] = mapped_column(Integer, default=1)

    # HF modem configuration
    hf_modem_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)   # harris/codan/barrett
    hf_frequency_mhz: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hf_link_encrypted: Mapped[bool] = mapped_column(Boolean, default=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
