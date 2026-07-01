"""
Full auth.py — adds /register and /users endpoints
to the existing login + /me routes.
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
import secrets
import string
from sqlalchemy import select

from app.config import get_settings
from app.database import get_db
from app.models.user import User, AccessRequest
from app.schemas.user import (
    TokenOut, UserOut, UserCreate,
    AccessRequestCreate, AccessRequestOut, AcceptBody, RejectBody,
)
from app.core.security import PasswordPolicy, AuditLogger
from pydantic import BaseModel

cfg = get_settings()
router = APIRouter()

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


class PasswordSetupBody(BaseModel):
    current_password: str
    new_password: str


# ── Helpers ───────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return pwd_ctx.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)

def create_access_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(
        minutes=cfg.access_token_expire_minutes
    )
    return jwt.encode(payload, cfg.secret_key, algorithm=cfg.algorithm)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, cfg.secret_key, algorithms=[cfg.algorithm])
        user_id: str = payload.get("sub")
        if not user_id:
            raise exc
    except JWTError:
        raise exc

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise exc
    return user


# ── Routes ────────────────────────────────────────────────────────

@router.post("/token", response_model=TokenOut)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(User).where(User.username == form.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form.password, user.hashed_password):
        await AuditLogger(db).login_failed(form.username, "unknown")
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    token = create_access_token({"sub": str(user.id), "role": user.role})
    await AuditLogger(db).login_success(user.id, "unknown")
    return TokenOut(access_token=token, token_type="bearer", role=user.role)


@router.get("/me", response_model=UserOut)
async def me(current: Annotated[User, Depends(get_current_user)]):
    return current


@router.post("/setup-password")
async def setup_password(
    body: PasswordSetupBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    if not verify_password(body.current_password, current.hashed_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    PasswordPolicy.enforce(body.new_password)
    current.hashed_password = hash_password(body.new_password)
    db.add(current)
    await db.commit()
    await AuditLogger(db).user_password_changed(current.id)
    return {"message": "Password updated"}


@router.post("/register", response_model=UserOut, status_code=201)
async def register(
    body: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    """Admin-only: create a new user account."""
    if current.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    # Enforce password policy before hashing
    PasswordPolicy.enforce(body.password)

    exists = await db.execute(
        select(User).where((User.username == body.username) | (User.email == body.email))
    )
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username or email already exists")

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        is_active=body.is_active,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    await AuditLogger(db).user_created(current.id, user.id, body.role)
    return user


@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    if current.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    result = await db.execute(select(User).order_by(User.id))
    return result.scalars().all()


# ── Access Requests ───────────────────────────────────────────────

def _make_temp_password() -> str:
    """Generate a password that satisfies PasswordPolicy (≥10 chars, upper+lower+digit+special)."""
    upper = ''.join(secrets.choice(string.ascii_uppercase) for _ in range(2))
    lower = ''.join(secrets.choice(string.ascii_lowercase) for _ in range(5))
    digits = ''.join(secrets.choice(string.digits) for _ in range(3))
    return upper + lower + '@' + digits   # e.g. "ABabcde@123" = 11 chars


@router.post("/request-access", status_code=201)
async def request_access(
    body: AccessRequestCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Public endpoint — submit an account creation request."""
    existing = await db.execute(
        select(AccessRequest).where(
            (AccessRequest.username == body.username) &
            (AccessRequest.status == "pending")
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A pending request for this username already exists")

    req = AccessRequest(**body.model_dump())
    db.add(req)
    await db.flush()
    await db.refresh(req)
    return {"message": "Request submitted successfully", "id": req.id}


@router.get("/access-requests", response_model=list[AccessRequestOut])
async def list_access_requests(
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    """Admin only — list all access requests ordered by creation date."""
    if current.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    result = await db.execute(
        select(AccessRequest).order_by(AccessRequest.created_at.desc())
    )
    return result.scalars().all()


@router.post("/access-requests/{req_id}/accept", response_model=AccessRequestOut)
async def accept_access_request(
    req_id: int,
    body: AcceptBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    """Admin only — create user account and mark request approved."""
    if current.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    req = await db.get(AccessRequest, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Access request not found")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"Request is already {req.status}")

    # Check the username isn't already taken
    taken = await db.execute(select(User).where(User.username == req.username))
    if taken.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Username '{req.username}' is already registered")

    role = body.role_override or req.requested_role
    temp_pwd = _make_temp_password()

    user = User(
        username=req.username,
        email=req.email,
        hashed_password=hash_password(temp_pwd),
        full_name=req.full_name,
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    req.status = "approved"
    req.reviewed_at = datetime.now(timezone.utc)
    req.admin_note = body.admin_note or "Account created by administrator."
    req.temp_password = temp_pwd   # stored so admin can relay to the user

    await db.flush()
    await db.refresh(req)
    await AuditLogger(db).user_created(current.id, user.id, role)
    return req


@router.post("/access-requests/{req_id}/reject", response_model=AccessRequestOut)
async def reject_access_request(
    req_id: int,
    body: RejectBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    """Admin only — reject a pending access request."""
    if current.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    req = await db.get(AccessRequest, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Access request not found")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"Request is already {req.status}")

    req.status = "rejected"
    req.reviewed_at = datetime.now(timezone.utc)
    req.admin_note = body.admin_note or "Request rejected by administrator."
    await db.flush()
    await db.refresh(req)
    return req


# ── Bootstrap: create default admin if no users exist ─────────────

async def ensure_default_admin(db: AsyncSession):
    result = await db.execute(select(User))
    if result.first() is None:
        admin = User(
            username="admin",
            email="admin@dronearjuna.local",
            hashed_password=hash_password("Admin@1234"),
            full_name="System Administrator",
            role="admin",
            is_active=True,
        )
        db.add(admin)
        await db.commit()
        print("✓ Default admin created — username: admin  password: Admin@1234")
        print("  Change this immediately in Settings → Users")