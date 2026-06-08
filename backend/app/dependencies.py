"""
Shared FastAPI dependencies injected across all module routers.

Keep this file for cross-cutting concerns only — auth, pagination,
Redis, and common query filters. Module-specific logic stays in
each module's own router or service file.
"""
from typing import Annotated, Optional
from fastapi import Depends, Query, HTTPException, status
import redis.asyncio as aioredis

from app.config import get_settings
from app.database import AsyncSessionLocal, TSSessionLocal
from app.core.auth import get_current_user
from app.models.user import User

cfg = get_settings()


# ── Database sessions ─────────────────────────────────────────────
# These duplicate what's in database.py intentionally:
# routers import from dependencies, not database directly,
# keeping the import surface consistent.

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_ts_db():
    async with TSSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Redis client ──────────────────────────────────────────────────

_redis_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """
    Returns a shared async Redis connection.
    Lazily initialised on first use.
    """
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            cfg.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
        )
    return _redis_pool


# ── Common pagination parameters ─────────────────────────────────

class PaginationParams:
    def __init__(
        self,
        skip:  int = Query(default=0,    ge=0,   description="Records to skip"),
        limit: int = Query(default=50,   ge=1, le=500, description="Max records to return"),
    ):
        self.skip  = skip
        self.limit = limit


# ── Common date-range filter ──────────────────────────────────────

class DateRangeParams:
    from_dt: Optional[str]
    to_dt:   Optional[str]

    def __init__(
        self,
        from_dt: Optional[str] = Query(default=None, description="ISO 8601 start datetime"),
        to_dt:   Optional[str] = Query(default=None, description="ISO 8601 end datetime"),
    ):
        self.from_dt = from_dt
        self.to_dt   = to_dt


# ── Typed dependency aliases ──────────────────────────────────────
# Import these in routers instead of spelling out the full Depends(...)

CurrentUser  = Annotated[User, Depends(get_current_user)]
DbSession    = Annotated[object, Depends(get_db)]
TsSession    = Annotated[object, Depends(get_ts_db)]
RedisClient  = Annotated[aioredis.Redis, Depends(get_redis)]
Pagination   = Annotated[PaginationParams, Depends()]
DateRange    = Annotated[DateRangeParams, Depends()]