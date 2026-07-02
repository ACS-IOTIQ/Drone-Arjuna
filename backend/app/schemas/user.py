from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: str = ""
    role: str = "viewer"
    is_active: bool = True

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        allowed = {"admin", "mission_commander", "flight_controller", "viewer"}
        if v not in allowed:
            raise ValueError(f"role must be one of {allowed}")
        return v

    @field_validator("username")
    @classmethod
    def username_no_spaces(cls, v: str) -> str:
        if " " in v:
            raise ValueError("username must not contain spaces")
        return v.lower()


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


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
    must_change_password: bool = False


class TokenPayload(BaseModel):
    sub: str           # user id as string
    role: str
    exp: int           # unix timestamp


class AccessRequestCreate(BaseModel):
    username: str
    full_name: str
    email: EmailStr
    mobile: Optional[str] = None
    requested_role: str = "viewer"
    reason: Optional[str] = None

    @field_validator("requested_role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        allowed = {"admin", "mission_commander", "flight_controller", "viewer"}
        if v not in allowed:
            raise ValueError(f"requested_role must be one of {allowed}")
        return v

    @field_validator("username")
    @classmethod
    def username_no_spaces(cls, v: str) -> str:
        if " " in v:
            raise ValueError("username must not contain spaces")
        return v.lower()


class AccessRequestOut(BaseModel):
    id: int
    username: str
    full_name: str
    email: str
    mobile: Optional[str] = None
    requested_role: str
    reason: Optional[str] = None
    status: str
    admin_note: Optional[str] = None
    temp_password: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AcceptBody(BaseModel):
    admin_note: Optional[str] = None
    role_override: Optional[str] = None


class RejectBody(BaseModel):
    admin_note: Optional[str] = None