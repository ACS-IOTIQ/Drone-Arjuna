"""
Full auth.py — adds /register and /users endpoints
to the existing login + /me routes.
"""
import asyncio
import hashlib
import json
import secrets
import string
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import jwt
from jwt import PyJWTError as JWTError
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.user import User, AccessRequest
from app.schemas.user import (
    ForgotPasswordRequest, ResetPasswordRequest,
    TokenOut, UserOut, UserCreate, RefreshRequest, RefreshOut,
    MfaChallengeOut, MfaVerifyRequest, MfaSetupOut, MfaCodeRequest, MfaDisableRequest,
    AccessRequestCreate, AccessRequestOut, AcceptBody, RejectBody,
)
from app.core.security import (
    PasswordPolicy, AuditLogger, TokenBlacklist, LoginLockout,
    get_redis, client_ip, rate_limit,
)
from app.core import totp
from app.core.email import send_approval_email, send_password_reset_email, send_reset_link_email
from pydantic import BaseModel

cfg = get_settings()
router = APIRouter()

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

# Verified against when the username is unknown so response time does not
# reveal which usernames exist.
_DUMMY_HASH = pwd_ctx.hash("dummy-password-for-timing-equalisation")

ACCESS = "access"
REFRESH = "refresh"
MFA = "mfa"          # short-lived token proving the password step; exchanged at /mfa/verify
MFA_TOKEN_MINUTES = 5

# Browser sessions use HttpOnly cookies (invisible to scripts, so XSS cannot
# steal them). API clients may still send "Authorization: Bearer". Requests
# authenticated by cookie that change state must carry this custom header,
# which a cross-site form or <img> cannot set (CSRF defence, on top of
# SameSite=Strict).
ACCESS_COOKIE = "da_access"
REFRESH_COOKIE = "da_refresh"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "DroneArjuna"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class PasswordSetupBody(BaseModel):
    current_password: str
    new_password: str


class LogoutBody(BaseModel):
    refresh_token: Optional[str] = None


# -- Helpers -------------------------------------------------------

def hash_password(plain: str) -> str:
    return pwd_ctx.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    # bcrypt only uses the first 72 bytes; reject absurd inputs outright.
    if len(plain) > PasswordPolicy.MAX_LENGTH:
        return False
    return pwd_ctx.verify(plain, hashed)


def _make_token(data: dict, token_type: str, lifetime: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = data.copy()
    payload.update({
        "type": token_type,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": now + lifetime,
    })
    return jwt.encode(payload, cfg.secret_key, algorithm=cfg.algorithm)


def create_access_token(data: dict) -> str:
    return _make_token(data, ACCESS, timedelta(minutes=cfg.access_token_expire_minutes))


def create_refresh_token(data: dict) -> str:
    return _make_token(data, REFRESH, timedelta(days=cfg.refresh_token_expire_days))


def _unauth() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _decode(token: str, expected_type: str) -> dict:
    """Verify signature, expiry, token type and revocation. Raises 401."""
    try:
        payload = jwt.decode(token, cfg.secret_key, algorithms=[cfg.algorithm])
    except JWTError:
        raise _unauth()
    if payload.get("type") != expected_type or not payload.get("sub") or not payload.get("jti"):
        raise _unauth()
    try:
        uid = int(payload["sub"])
    except (TypeError, ValueError):
        raise _unauth()

    bl = TokenBlacklist(get_redis())
    if await bl.is_revoked(payload["jti"]):
        raise _unauth()
    revoked_at = await bl.user_revoked_at(uid)
    if revoked_at is not None and int(payload.get("iat", 0)) <= revoked_at:
        raise _unauth()
    return payload


async def get_current_user_from_token(
    token: str, db: AsyncSession, expected_type: str = ACCESS,
) -> User:
    """Shared by the REST dependency and WebSocket handlers."""
    payload = await _decode(token, expected_type)
    result = await db.execute(select(User).where(User.id == int(payload["sub"])))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise _unauth()
    return user


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def _set_auth_cookies(response: Response, request: Request,
                      access: Optional[str] = None, refresh: Optional[str] = None) -> None:
    secure = _is_https(request)
    if access:
        response.set_cookie(ACCESS_COOKIE, access, httponly=True, secure=secure, samesite="strict",
                            max_age=cfg.access_token_expire_minutes * 60, path="/")
    if refresh:
        # Only ever sent to the auth endpoints.
        response.set_cookie(REFRESH_COOKIE, refresh, httponly=True, secure=secure, samesite="strict",
                            max_age=cfg.refresh_token_expire_days * 86400, path="/api/auth")


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


def _require_csrf_header(request: Request) -> None:
    if request.method in _SAFE_METHODS:
        return
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(status_code=403, detail="Missing CSRF header")


async def access_token_from_request(
    request: Request,
    bearer: Annotated[Optional[str], Depends(oauth2_scheme)],
) -> str:
    """Bearer header wins; otherwise the HttpOnly cookie (with CSRF header check)."""
    if bearer:
        return bearer
    cookie = request.cookies.get(ACCESS_COOKIE)
    if not cookie:
        raise _unauth()
    _require_csrf_header(request)
    return cookie


async def get_current_user(
    token: Annotated[str, Depends(access_token_from_request)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    return await get_current_user_from_token(token, db, ACCESS)


# -- WebSocket auth: single-use short-lived tickets ----------------

TICKET_TTL_SECONDS = 30
_ROLE_RANK = {"viewer": 1, "flight_controller": 2, "mission_commander": 3, "admin": 4}


async def authenticate_ws(ws: WebSocket, db: AsyncSession, min_role: Optional[str] = None) -> User:
    """
    Authenticate a WebSocket handshake via ?ticket=<single-use> issued by
    POST /api/auth/ws-ticket. JWTs in the query string are rejected so they
    never reach access logs. Raises HTTPException; callers close with
    4401/4403 before accept().
    """
    ticket = ws.query_params.get("ticket")
    user: Optional[User] = None
    if ticket:
        try:
            uid = await get_redis().getdel(f"wsticket:{ticket}")
        except Exception:
            raise _unauth()
        if not uid:
            raise _unauth()
        user = await db.get(User, int(uid))
        if not user or not user.is_active:
            raise _unauth()
    else:
        raise _unauth()

    if min_role and _ROLE_RANK.get(user.role, 0) < _ROLE_RANK[min_role]:
        raise HTTPException(status_code=403, detail="Forbidden")
    return user


@router.post("/ws-ticket")
async def ws_ticket(current: Annotated[User, Depends(get_current_user)]):
    """Issue a single-use, 30-second ticket for opening a WebSocket."""
    ticket = secrets.token_urlsafe(32)
    try:
        await get_redis().setex(f"wsticket:{ticket}", TICKET_TTL_SECONDS, str(current.id))
    except Exception:
        raise HTTPException(status_code=503, detail="Ticket service unavailable")
    return {"ticket": ticket, "expires_in": TICKET_TTL_SECONDS}


async def revoke_user_sessions(user_id: int) -> None:
    await TokenBlacklist(get_redis()).revoke_all_for_user(user_id)


# -- Routes --------------------------------------------------------

async def _issue_session(response: Response, request: Request, user: User) -> TokenOut:
    access = create_access_token({"sub": str(user.id), "role": user.role})
    refresh_tok = create_refresh_token({"sub": str(user.id)})
    _set_auth_cookies(response, request, access, refresh_tok)
    return TokenOut(
        access_token=access,
        refresh_token=refresh_tok,
        token_type="bearer",
        role=user.role,
        must_change_password=user.must_change_password,
        mfa_enrollment_required=(user.role in cfg.mfa_required_roles and not user.totp_enabled),
    )


@router.post("/token", response_model=Union[TokenOut, MfaChallengeOut],
             dependencies=[Depends(rate_limit("login", 20, 60))])
async def login(
    request: Request,
    response: Response,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ip = client_ip(request)
    await LoginLockout.check(form.username)

    result = await db.execute(select(User).where(User.username == form.username.lower()))
    user = result.scalar_one_or_none()
    # Always run one bcrypt verification so timing does not leak user existence.
    ok = verify_password(form.password, user.hashed_password if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active:
        await LoginLockout.fail(form.username)
        await AuditLogger(db).login_failed(form.username, ip)
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    await LoginLockout.clear(form.username)
    if user.totp_enabled:
        # Password accepted, second factor still outstanding: no session, no cookies.
        await AuditLogger(db).log(AuditLogger.AUTH, "password_ok_mfa_pending",
                                  user_id=user.id, ip_address=ip)
        return MfaChallengeOut(mfa_token=_make_token(
            {"sub": str(user.id)}, MFA, timedelta(minutes=MFA_TOKEN_MINUTES)))
    await AuditLogger(db).login_success(user.id, ip)
    return await _issue_session(response, request, user)


@router.post("/refresh", response_model=RefreshOut,
             dependencies=[Depends(rate_limit("refresh", 30, 60))])
async def refresh(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    body: RefreshRequest = RefreshRequest(),
):
    refresh_tok = body.refresh_token
    if not refresh_tok:
        refresh_tok = request.cookies.get(REFRESH_COOKIE)
        if not refresh_tok:
            raise _unauth()
        _require_csrf_header(request)
    user = await get_current_user_from_token(refresh_tok, db, REFRESH)
    access = create_access_token({"sub": str(user.id), "role": user.role})
    _set_auth_cookies(response, request, access=access)
    return RefreshOut(access_token=access)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    token: Annotated[str, Depends(access_token_from_request)],
    db: Annotated[AsyncSession, Depends(get_db)],
    body: LogoutBody = LogoutBody(),
):
    user = await get_current_user_from_token(token, db, ACCESS)
    bl = TokenBlacklist(get_redis())
    for t in (token, body.refresh_token or request.cookies.get(REFRESH_COOKIE)):
        if not t:
            continue
        try:
            p = jwt.decode(t, cfg.secret_key, algorithms=[cfg.algorithm])
        except JWTError:
            continue
        if p.get("sub") != str(user.id) or not p.get("jti"):
            continue
        await bl.revoke(p["jti"], max(int(p.get("exp", 0)) - int(time.time()), 1))
    await AuditLogger(db).logout(user.id, client_ip(request))
    _clear_auth_cookies(response)
    return {"message": "Logged out"}


# -- Multi-factor authentication (TOTP) ----------------------------

async def _check_second_factor(user: User, code: str, db: AsyncSession) -> bool:
    """Accept a current TOTP code (single use) or an unused recovery code."""
    if not user.totp_enabled or not user.totp_secret_enc:
        return False
    try:
        secret = totp.decrypt_secret(user.totp_secret_enc)
    except ValueError:
        return False
    step = totp.verify_totp(secret, code, last_step=user.totp_last_step)
    if step is not None:
        user.totp_last_step = step                      # replay protection
        await db.commit()
        return True
    remaining = totp.consume_recovery_code(code, json.loads(user.recovery_codes or "[]"))
    if remaining is not None:
        user.recovery_codes = json.dumps(remaining)
        await db.commit()
        return True
    return False


@router.post("/mfa/verify", response_model=TokenOut,
             dependencies=[Depends(rate_limit("mfa_verify", 10, 60))])
async def mfa_verify(
    body: MfaVerifyRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Second login step: exchange the MFA token + authenticator/recovery code for a session."""
    payload = await _decode(body.mfa_token, MFA)
    user = await db.get(User, int(payload["sub"]))
    if not user or not user.is_active or not user.totp_enabled:
        raise _unauth()
    ip = client_ip(request)

    # Separate counter from the password lockout: otherwise someone who knows the
    # password could reset it with every login and guess codes indefinitely.
    lock_name = f"mfa:{user.username}"
    await LoginLockout.check(lock_name)
    if not await _check_second_factor(user, body.code, db):
        await LoginLockout.fail(lock_name)
        await AuditLogger(db).log(AuditLogger.AUTH, "mfa_failed", user_id=user.id,
                                  ip_address=ip, severity="WARNING")
        raise HTTPException(status_code=401, detail="Invalid authentication code")

    await LoginLockout.clear(lock_name)
    # The MFA token is single use.
    await TokenBlacklist(get_redis()).revoke(
        payload["jti"], max(int(payload.get("exp", 0)) - int(time.time()), 1))
    await AuditLogger(db).login_success(user.id, ip)
    return await _issue_session(response, request, user)


@router.post("/mfa/setup", response_model=MfaSetupOut)
async def mfa_setup(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Start enrolment: returns a fresh secret (not active until /mfa/enable confirms a code)."""
    if current.totp_enabled:
        raise HTTPException(status_code=409, detail="MFA is already enabled")
    secret = totp.generate_secret()
    current.totp_secret_enc = totp.encrypt_secret(secret)
    current.totp_last_step = None
    await db.commit()
    return MfaSetupOut(secret=secret, otpauth_uri=totp.provisioning_uri(secret, current.username))


@router.post("/mfa/enable")
async def mfa_enable(
    body: MfaCodeRequest,
    request: Request,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Confirm enrolment with a code from the authenticator app; returns one-time recovery codes."""
    if current.totp_enabled:
        raise HTTPException(status_code=409, detail="MFA is already enabled")
    if not current.totp_secret_enc:
        raise HTTPException(status_code=400, detail="Call /mfa/setup first")
    step = totp.verify_totp(totp.decrypt_secret(current.totp_secret_enc), body.code)
    if step is None:
        raise HTTPException(status_code=400, detail="Invalid authentication code")
    codes = totp.generate_recovery_codes()
    current.totp_enabled = True
    current.totp_last_step = step
    current.recovery_codes = json.dumps([totp.hash_recovery_code(c) for c in codes])
    await db.commit()
    await AuditLogger(db).log(AuditLogger.USER, "mfa_enabled", user_id=current.id,
                              ip_address=client_ip(request), severity="WARNING")
    return {"detail": "MFA enabled", "recovery_codes": codes}


@router.post("/mfa/recovery-codes")
async def mfa_regenerate_recovery_codes(
    body: MfaCodeRequest,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Replace the recovery codes (old ones stop working). Requires a valid code."""
    if not await _check_second_factor(current, body.code, db):
        raise HTTPException(status_code=400, detail="Invalid authentication code")
    codes = totp.generate_recovery_codes()
    current.recovery_codes = json.dumps([totp.hash_recovery_code(c) for c in codes])
    await db.commit()
    return {"recovery_codes": codes}


@router.post("/mfa/disable")
async def mfa_disable(
    body: MfaDisableRequest,
    request: Request,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Turn MFA off. Needs the password AND a valid code, so a stolen session cannot do it."""
    if not current.totp_enabled:
        raise HTTPException(status_code=400, detail="MFA is not enabled")
    if not verify_password(body.password, current.hashed_password):
        raise HTTPException(status_code=403, detail="Invalid credentials")
    if not await _check_second_factor(current, body.code, db):
        raise HTTPException(status_code=403, detail="Invalid credentials")
    current.totp_enabled = False
    current.totp_secret_enc = None
    current.totp_last_step = None
    current.recovery_codes = None
    await db.commit()
    await revoke_user_sessions(current.id)
    await AuditLogger(db).log(AuditLogger.USER, "mfa_disabled", user_id=current.id,
                              ip_address=client_ip(request), severity="WARNING")
    return {"detail": "MFA disabled"}


@router.post("/users/{user_id}/mfa/reset")
async def admin_reset_mfa(
    user_id: int,
    request: Request,
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Admin recovery for a lost authenticator: clears the user's MFA and ends their sessions."""
    if current.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.totp_enabled = False
    target.totp_secret_enc = None
    target.totp_last_step = None
    target.recovery_codes = None
    await db.commit()
    await revoke_user_sessions(target.id)
    await AuditLogger(db).log(AuditLogger.USER, "mfa_reset_by_admin", user_id=current.id,
                              ip_address=client_ip(request), severity="WARNING",
                              detail={"target_user_id": target.id})
    return {"detail": "MFA reset"}


RESET_TOKEN_TTL_MINUTES = 30
_FORGOT_MSG = "If that email is registered, a reset link has been sent."


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/forgot-password", dependencies=[Depends(rate_limit("forgot", 5, 3600))])
async def forgot_password(body: ForgotPasswordRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    """Always returns the same message so registered emails cannot be enumerated."""
    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if user and user.is_active and cfg.smtp_enabled:
        raw = secrets.token_urlsafe(32)
        user.reset_token = hash_reset_token(raw)   # only the hash is stored
        user.reset_token_expires = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)
        db.add(user)
        await db.commit()
        asyncio.create_task(send_reset_link_email(user.email, user.full_name or user.username, user.username, raw))
    return {"message": _FORGOT_MSG}


@router.post("/reset-password", dependencies=[Depends(rate_limit("reset", 10, 3600))])
async def reset_password(body: ResetPasswordRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    user = (await db.execute(
        select(User).where(User.reset_token == hash_reset_token(body.token))
    )).scalar_one_or_none()
    expires = user.reset_token_expires if user else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if not user or not user.is_active or not expires or expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    PasswordPolicy.enforce(body.new_password)
    user.hashed_password = hash_password(body.new_password)
    user.must_change_password = False
    user.reset_token = None            # single use
    user.reset_token_expires = None
    db.add(user)
    await db.commit()
    await revoke_user_sessions(user.id)
    await AuditLogger(db).log("user", "password_reset_via_token", user_id=user.id, severity="WARNING")
    return {"message": "Password has been reset"}


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
    current.must_change_password = False
    db.add(current)
    await db.commit()
    await AuditLogger(db).user_password_changed(current.id)
    await revoke_user_sessions(current.id)
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


@router.post("/users/{user_id}/reset-password", status_code=200)
async def reset_user_password(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    if current.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    if not cfg.smtp_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMTP is disabled; password reset email cannot be sent",
        )

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    temp_pwd = _make_temp_password()
    user.hashed_password = hash_password(temp_pwd)
    user.must_change_password = True
    db.add(user)
    await db.commit()
    await revoke_user_sessions(user.id)
    await AuditLogger(db).user_password_changed(user.id)

    asyncio.create_task(
        send_password_reset_email(
            to_email=user.email,
            full_name=user.full_name or user.username,
            username=user.username,
            temp_password=temp_pwd,
        )
    )
    return {"message": f"Password reset email queued for {user.email}"}


# ── Access Requests ───────────────────────────────────────────────

def _make_temp_password() -> str:
    """16 random chars satisfying PasswordPolicy (upper, lower, digit, special)."""
    pools = [string.ascii_uppercase, string.ascii_lowercase, string.digits, "!@#$%^&*-_=+"]
    chars = [secrets.choice(p) for p in pools]
    alphabet = "".join(pools)
    chars += [secrets.choice(alphabet) for _ in range(12)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


@router.post("/request-access", status_code=201,
             dependencies=[Depends(rate_limit("request_access", 5, 3600))])
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
    dup = existing.scalars().first()
    if dup:
        # Identical response shape to a fresh submission: do not reveal whether
        # a request for this username already exists.
        return {"message": "Request submitted successfully", "id": dup.id}

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

    # Check username and email aren't already taken
    taken_user = await db.execute(select(User).where(User.username == req.username))
    if taken_user.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Username '{req.username}' is already registered")

    taken_email = await db.execute(select(User).where(User.email == req.email))
    if taken_email.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Email '{req.email}' is already registered to another account")

    role = body.role_override or "viewer"  # requested_role is advisory only
    if role not in {"admin", "mission_commander", "flight_controller", "viewer"}:
        raise HTTPException(status_code=422, detail="Invalid role")
    temp_pwd = _make_temp_password()

    user = User(
        username=req.username,
        email=req.email,
        hashed_password=hash_password(temp_pwd),
        full_name=req.full_name,
        role=role,
        is_active=True,
        must_change_password=True,
    )
    db.add(user)
    await db.flush()

    req.status = "approved"
    req.reviewed_at = datetime.now(timezone.utc)
    req.admin_note = body.admin_note or "Account created by administrator."
    req.temp_password = None   # never persisted; delivered once by email

    await db.flush()
    await db.refresh(req)
    await AuditLogger(db).user_created(current.id, user.id, role)

    # Fire approval email — failure is logged but never raises
    asyncio.create_task(
        send_approval_email(
            to_email=req.email,
            full_name=req.full_name,
            username=req.username,
            temp_password=temp_pwd,
            role=role,
        )
    )

    return req


@router.post("/access-requests/{req_id}/resend-email", status_code=200)
async def resend_approval_email(
    req_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
):
    """Admin only — re-send the approval email for an approved request."""
    if current.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    req = await db.get(AccessRequest, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Access request not found")
    if req.status != "approved":
        raise HTTPException(status_code=409, detail="Email can only be resent for approved requests")
    user = (await db.execute(select(User).where(User.username == req.username))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User account not found")
    temp_pwd = _make_temp_password()
    user.hashed_password = hash_password(temp_pwd)
    user.must_change_password = True
    db.add(user)
    await db.commit()
    await revoke_user_sessions(user.id)

    asyncio.create_task(
        send_approval_email(
            to_email=req.email,
            full_name=req.full_name,
            username=req.username,
            temp_password=temp_pwd,
            role=user.role,
        )
    )
    return {"message": f"Approval email queued for {req.email}"}


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
    """
    First-run bootstrap: creates 'admin' with a random one-time password that
    is shown once on the console and must be changed at first login.
    Set BOOTSTRAP_ADMIN_PASSWORD to supply your own (policy-checked).
    """
    import os
    result = await db.execute(select(User))
    if result.first() is not None:
        return
    supplied = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD")
    pwd = supplied or _make_temp_password()
    PasswordPolicy.enforce(pwd)
    db.add(User(
        username="admin",
        email="admin@dronearjuna.local",
        hashed_password=hash_password(pwd),
        full_name="System Administrator",
        role="admin",
        is_active=True,
        must_change_password=True,
    ))
    await db.commit()
    if not supplied:
        print(f"[bootstrap] admin account created. One-time password (shown once): {pwd}")
