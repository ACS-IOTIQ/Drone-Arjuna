# ═══════════════════════════════════════════
# app/models/user.py
# ═══════════════════════════════════════════
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(128))
    full_name: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(32), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class AccessRequest(Base):
    """Account creation requests submitted from the login screen."""
    __tablename__ = "access_requests"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(128), nullable=False)
    mobile: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    requested_role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # pending | approved | rejected
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    admin_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    temp_password: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# ═══════════════════════════════════════════
# app/schemas/user.py
# ═══════════════════════════════════════════
from pydantic import BaseModel, EmailStr
from datetime import datetime


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: str = ""
    role: str = "viewer"


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str
    role: str