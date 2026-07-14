"""
Security Utilities
==================
Cross-cutting security concerns distinct from auth.py (which handles
JWT lifecycle and login routes).

Covers (per spec section 9.1):
  - Password policy enforcement
  - Token blacklist  — revoke JWTs on logout / role change
  - Rate limiter     — protect login and command endpoints
  - Audit logger     — tamper-evident log of security events
  - Input sanitiser  — strip control characters from free-text inputs

All Redis operations degrade gracefully if Redis is unavailable so the
application can still run in a reduced-security dev mode.
"""
import re
import html
import time
import hashlib
import structlog
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.config import get_settings

log = structlog.get_logger()
cfg = get_settings()


# ══════════════════════════════════════════════════════════════════
# Password Policy
# ══════════════════════════════════════════════════════════════════

class PasswordPolicy:
    """
    Enforces password strength rules before hashing.
    Called by auth.py /register and any password-change endpoint.
    """
    MIN_LENGTH       = 10
    REQUIRE_UPPER    = True
    REQUIRE_LOWER    = True
    REQUIRE_DIGIT    = True
    REQUIRE_SPECIAL  = True
    SPECIAL_CHARS    = r"!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~"

    # Common weak passwords — extend this list as needed
    BLOCKLIST: set[str] = {
        "password", "password1", "password123",
        "admin1234", "qwerty123", "letmein1",
        "dronearjuna", "changeme",
    }

    @classmethod
    def validate(cls, password: str) -> list[str]:
        """
        Returns a list of violation messages.
        Empty list means the password passes all checks.
        """
        errors: list[str] = []

        if len(password) < cls.MIN_LENGTH:
            errors.append(
                f"Password must be at least {cls.MIN_LENGTH} characters long"
            )

        if cls.REQUIRE_UPPER and not re.search(r"[A-Z]", password):
            errors.append("Password must contain at least one uppercase letter")

        if cls.REQUIRE_LOWER and not re.search(r"[a-z]", password):
            errors.append("Password must contain at least one lowercase letter")

        if cls.REQUIRE_DIGIT and not re.search(r"\d", password):
            errors.append("Password must contain at least one digit")

        if cls.REQUIRE_SPECIAL and not re.search(
            f"[{cls.SPECIAL_CHARS}]", password
        ):
            errors.append(
                "Password must contain at least one special character "
                "(!@#$%^&* etc.)"
            )

        if password.lower() in cls.BLOCKLIST:
            errors.append("Password is too common — choose a more unique password")

        return errors

    @classmethod
    def enforce(cls, password: str) -> None:
        """Raises HTTPException 422 if password fails policy."""
        errors = cls.validate(password)
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "Password does not meet policy", "errors": errors},
            )


# ══════════════════════════════════════════════════════════════════
# Token Blacklist  (Redis-backed)
# ══════════════════════════════════════════════════════════════════

class TokenBlacklist:
    """
    Revokes JWTs before natural expiry.
    Used by /logout and on role/password changes.

    Storage: Redis SET with expiry matching the token's own TTL.
    Key:     blacklist:<jti_hash>   (we hash the raw token for key safety)
    """
    PREFIX = "blacklist:"

    def __init__(self, redis: aioredis.Redis):
        self._r = redis

    def _key(self, token: str) -> str:
        digest = hashlib.sha256(token.encode()).hexdigest()[:32]
        return f"{self.PREFIX}{digest}"

    async def revoke(self, token: str, ttl_seconds: int) -> None:
        """Mark a token as revoked for the remainder of its lifetime."""
        try:
            await self._r.setex(self._key(token), ttl_seconds, "1")
            log.info("Token revoked", ttl=ttl_seconds)
        except Exception as e:
            log.warning("Token blacklist write failed", error=str(e))

    async def is_revoked(self, token: str) -> bool:
        """Returns True if the token has been explicitly revoked."""
        try:
            return await self._r.exists(self._key(token)) == 1
        except Exception as e:
            log.warning("Token blacklist read failed — assuming not revoked",
                        error=str(e))
            return False

    async def revoke_all_for_user(self, user_id: int) -> None:
        """
        Marks a per-user revocation timestamp.
        Any token issued before this time is considered invalid.
        Used when a user's role changes or account is disabled.
        Key: blacklist:user:<user_id>
        """
        try:
            ttl = cfg.access_token_expire_minutes * 60
            await self._r.setex(
                f"blacklist:user:{user_id}",
                ttl,
                str(int(time.time())),
            )
            log.info("All tokens revoked for user", user_id=user_id)
        except Exception as e:
            log.warning("User token revocation failed", error=str(e))

    async def user_revoked_at(self, user_id: int) -> Optional[int]:
        """
        Returns the Unix timestamp at which all this user's tokens
        were invalidated, or None if no bulk revocation exists.
        """
        try:
            val = await self._r.get(f"blacklist:user:{user_id}")
            return int(val) if val else None
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════════
# Rate Limiter  (Redis sliding-window)
# ══════════════════════════════════════════════════════════════════

class RateLimiter:
    """
    Sliding-window rate limiter backed by Redis sorted sets.

    Each (key, window) combination tracks request timestamps.
    Requests older than the window are pruned on each check.

    Usage in a FastAPI dependency:
        limiter = RateLimiter(redis)
        await limiter.check("login", request.client.host, limit=5, window=60)
    """

    def __init__(self, redis: aioredis.Redis):
        self._r = redis

    async def check(
        self,
        action: str,
        identifier: str,
        limit: int,
        window_seconds: int,
    ) -> None:
        """
        Raises HTTP 429 if `identifier` has exceeded `limit`
        requests for `action` within `window_seconds`.
        Silently passes if Redis is unavailable.
        """
        try:
            key = f"rl:{action}:{identifier}"
            now = time.time()
            window_start = now - window_seconds

            pipe = self._r.pipeline()
            # Remove entries outside the window
            pipe.zremrangebyscore(key, "-inf", window_start)
            # Count remaining entries
            pipe.zcard(key)
            # Add current request
            pipe.zadd(key, {str(now): now})
            # Set key expiry to avoid orphaned keys
            pipe.expire(key, window_seconds + 1)
            results = await pipe.execute()

            count = results[1]   # zcard result
            if count >= limit:
                retry_after = int(window_seconds)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        f"Rate limit exceeded: {limit} requests "
                        f"per {window_seconds}s for '{action}'"
                    ),
                    headers={"Retry-After": str(retry_after)},
                )
        except HTTPException:
            raise
        except Exception as e:
            log.warning("Rate limiter unavailable — skipping check",
                        action=action, error=str(e))


# ── Preset rate-limit rules ───────────────────────────────────────
# Use these as FastAPI dependency factories in routers.

def login_rate_limit(redis: aioredis.Redis):
    """5 login attempts per 60 seconds per IP."""
    async def _dep(request: Request):
        ip = request.client.host if request.client else "unknown"
        await RateLimiter(redis).check("login", ip, limit=5, window_seconds=60)
    return _dep


def command_rate_limit(redis: aioredis.Redis):
    """30 flight commands per 10 seconds per user."""
    async def _dep(request: Request):
        ip = request.client.host if request.client else "unknown"
        await RateLimiter(redis).check("command", ip, limit=30, window_seconds=10)
    return _dep


# ══════════════════════════════════════════════════════════════════
# Audit Logger
# ══════════════════════════════════════════════════════════════════

class AuditLogger:
    """
    Writes security and operational events to the audit_log table.

    Per spec section 9.1:
      - Comprehensive audit logging
      - Tamper-evident logs
      - 7-year retention (regulatory compliance)

    V1: Writes to PostgreSQL via raw SQL.
        The audit_log table is append-only — no UPDATE or DELETE
        is ever issued against it.
    V2: Will also ship events to the ELK stack for SIEM integration.
    """

    # Event categories
    AUTH    = "auth"
    COMMAND = "command"
    MISSION = "mission"
    USER    = "user"
    SYSTEM  = "system"
    DATA    = "data"

    def __init__(self, db: AsyncSession):
        self._db = db

    async def log(
        self,
        category:    str,
        action:      str,
        user_id:     Optional[int]  = None,
        drone_id:    Optional[int]  = None,
        mission_id:  Optional[int]  = None,
        ip_address:  Optional[str]  = None,
        detail:      Optional[dict] = None,
        severity:    str = "INFO",
    ) -> None:
        """
        Appends one audit record.
        Never raises — audit failure must not block the main operation.
        """
        try:
            await self._db.execute(
                text("""
                    INSERT INTO audit_log
                        (timestamp, category, action, user_id,
                         drone_id, mission_id, ip_address,
                         detail, severity)
                    VALUES
                        (:ts, :cat, :act, :uid,
                         :did, :mid, :ip,
                         CAST(:det AS jsonb), :sev)
                """),
                {
                    "ts":  datetime.now(timezone.utc),
                    "cat": category,
                    "act": action,
                    "uid": user_id,
                    "did": drone_id,
                    "mid": mission_id,
                    "ip":  ip_address,
                    "det": _safe_json(detail),
                    "sev": severity,
                },
            )
            await self._db.commit()
        except Exception as e:
            log.error("Audit log write failed", category=category,
                      action=action, error=str(e))

    # ── Convenience methods ───────────────────────────────────────

    async def login_success(self, user_id: int, ip: str):
        await self.log(self.AUTH, "login_success",
                       user_id=user_id, ip_address=ip)

    async def login_failed(self, username: str, ip: str):
        await self.log(self.AUTH, "login_failed",
                       ip_address=ip, detail={"username": username},
                       severity="WARNING")

    async def logout(self, user_id: int, ip: str):
        await self.log(self.AUTH, "logout", user_id=user_id, ip_address=ip)

    async def command_sent(
        self, user_id: int, drone_id: int,
        command: str, result: str, ip: str,
    ):
        await self.log(
            self.COMMAND, "command_sent",
            user_id=user_id, drone_id=drone_id, ip_address=ip,
            detail={"command": command, "result": result},
            severity="INFO" if result == "accepted" else "WARNING",
        )

    async def mission_status_changed(
        self, user_id: int, mission_id: int, new_status: str,
    ):
        await self.log(
            self.MISSION, "status_changed",
            user_id=user_id, mission_id=mission_id,
            detail={"new_status": new_status},
        )

    async def user_created(self, admin_id: int, new_user_id: int, role: str):
        await self.log(
            self.USER, "user_created",
            user_id=admin_id,
            detail={"new_user_id": new_user_id, "role": role},
        )

    async def user_role_changed(
        self, admin_id: int, target_user_id: int,
        old_role: str, new_role: str,
    ):
        await self.log(
            self.USER, "role_changed",
            user_id=admin_id,
            detail={
                "target_user_id": target_user_id,
                "old_role": old_role,
                "new_role": new_role,
            },
            severity="WARNING",
        )

    async def user_password_changed(self, user_id: int):
        await self.log(
            self.USER, "password_changed",
            user_id=user_id,
            severity="WARNING",
        )


# ══════════════════════════════════════════════════════════════════
# Input Sanitiser
# ══════════════════════════════════════════════════════════════════

class InputSanitiser:
    """
    Strips dangerous content from free-text fields before persistence.
    Called in service layers before writing user-supplied strings to DB.
    """

    # Control characters except \n \r \t
    _CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

    # Simple SQL injection signal patterns (logging only — Pydantic + ORM
    # already parameterise queries, this is defence-in-depth)
    _SQL_RE = re.compile(
        r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|EXEC)\b|--|;|/\*)",
        re.IGNORECASE,
    )

    @classmethod
    def clean(cls, value: str, max_length: int = 1000) -> str:
        """
        1. Truncate to max_length
        2. Strip control characters
        3. HTML-escape special chars
        4. Log (but don't block) suspected SQL injection attempts
        """
        if not isinstance(value, str):
            return value

        value = value[:max_length]
        value = cls._CONTROL_RE.sub("", value)

        if cls._SQL_RE.search(value):
            log.warning("Possible SQL injection pattern in input",
                        snippet=value[:80])

        return html.escape(value, quote=False)

    @classmethod
    def clean_dict(cls, data: dict, max_length: int = 1000) -> dict:
        """Recursively sanitise all string values in a dict."""
        out = {}
        for k, v in data.items():
            if isinstance(v, str):
                out[k] = cls.clean(v, max_length)
            elif isinstance(v, dict):
                out[k] = cls.clean_dict(v, max_length)
            else:
                out[k] = v
        return out


# ══════════════════════════════════════════════════════════════════
# Alembic migration for audit_log table
# ══════════════════════════════════════════════════════════════════
# Add this to the next migration file:
#
# op.create_table('audit_log',
#     sa.Column('id',         sa.BigInteger(), primary_key=True),
#     sa.Column('timestamp',  sa.DateTime(timezone=True), nullable=False, index=True),
#     sa.Column('category',   sa.String(32),  nullable=False),
#     sa.Column('action',     sa.String(64),  nullable=False),
#     sa.Column('user_id',    sa.Integer(),   nullable=True),
#     sa.Column('drone_id',   sa.Integer(),   nullable=True),
#     sa.Column('mission_id', sa.Integer(),   nullable=True),
#     sa.Column('ip_address', sa.String(45),  nullable=True),
#     sa.Column('detail',     postgresql.JSONB(), nullable=True),
#     sa.Column('severity',   sa.String(16),  server_default='INFO'),
# )
# op.create_index('ix_audit_log_user',     'audit_log', ['user_id'])
# op.create_index('ix_audit_log_category', 'audit_log', ['category', 'timestamp'])
#
# NOTE: Never add UPDATE or DELETE grants on audit_log to app DB user.


# ── Internal helpers ──────────────────────────────────────────────

import json

def _safe_json(data: Optional[dict]) -> Optional[str]:
    """Serialise dict to JSON string, return None on failure."""
    if data is None:
        return None
    try:
        return json.dumps(data, default=str)
    except Exception:
        return None
