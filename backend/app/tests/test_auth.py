"""
Authentication flow tests
=========================
Tests cover three categories:

  1. Login (POST /api/auth/token)
       - valid credentials → 200 + token
       - wrong password / unknown user → 401

  2. Token validation (GET /api/auth/me)
       - valid token → 200, correct user info returned
       - no token, malformed token → 401
       - token belonging to an inactive account → 401

  3. Token expiry
       - structurally-valid JWT whose `exp` is in the past → 401
"""
import pytest
from httpx import AsyncClient


# ═══════════════════════════════════════════════════════════════════════
# 1. Login
# ═══════════════════════════════════════════════════════════════════════

async def test_login_returns_access_token(client: AsyncClient, admin_user):
    """
    POST /api/auth/token with correct credentials must return HTTP 200
    and a body containing an access_token, token_type=='bearer', and
    the user's role.
    """
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin_test", "password": "Admin@1234"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert body["role"] == "admin"


async def test_login_wrong_password_is_401(client: AsyncClient, admin_user):
    """Wrong password must be rejected with HTTP 401."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "admin_test", "password": "BadPassword!99"},
    )
    assert resp.status_code == 401


async def test_login_unknown_user_is_401(client: AsyncClient):
    """
    A username that does not exist in the database must return 401
    (not 404 — we do not reveal whether an account exists).
    """
    resp = await client.post(
        "/api/auth/token",
        data={"username": "ghost_user", "password": "doesNotMatter@1"},
    )
    assert resp.status_code == 401


async def test_login_returns_role_for_flight_controller(
    client: AsyncClient, flight_controller_user
):
    """Token payload must carry the user's actual role."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "fc_test", "password": "FlightCtrl@99"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "flight_controller"


# ═══════════════════════════════════════════════════════════════════════
# 2. Token validation — GET /api/auth/me
# ═══════════════════════════════════════════════════════════════════════

async def test_me_returns_user_profile(
    client: AsyncClient, admin_user, make_token
):
    """
    A valid Bearer token must give back the authenticated user's profile
    with the correct username and role.
    """
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "admin_test"
    assert body["role"] == "admin"
    assert body["is_active"] is True


async def test_me_no_token_is_401(client: AsyncClient):
    """Request without an Authorization header must be rejected with 401."""
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_me_malformed_token_is_401(client: AsyncClient):
    """A syntactically invalid JWT string must return 401."""
    resp = await client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer this.is.clearly.not.a.jwt"},
    )
    assert resp.status_code == 401


async def test_me_wrong_signature_is_401(client: AsyncClient, admin_user):
    """
    A JWT signed with a different secret must be rejected even if the
    payload itself would be structurally valid.
    """
    from datetime import datetime, timedelta, timezone
    from jose import jwt as jose_jwt

    payload = {
        "sub": str(admin_user.id),
        "role": admin_user.role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
    }
    tampered_token = jose_jwt.encode(payload, "wrong_secret_key", algorithm="HS256")

    resp = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {tampered_token}"},
    )
    assert resp.status_code == 401


async def test_inactive_user_token_is_401_on_me(client: AsyncClient):
    """
    The login endpoint does not check is_active (by design — the token is
    still issued). However, get_current_user rejects tokens for inactive
    accounts, so GET /api/auth/me must return 401.
    """
    from app.core.auth import hash_password
    from app.models.user import User
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy.pool import StaticPool
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.tests.conftest import _TestSession

    # Create an inactive user directly in the test DB
    async with _TestSession() as session:
        inactive = User(
            username="inactive_da",
            email="inactive_da@da.local",
            hashed_password=hash_password("Active@Pass99"),
            role="viewer",
            is_active=False,
        )
        session.add(inactive)
        await session.commit()
        await session.refresh(inactive)
        uid = inactive.id

    try:
        # Login still works (login route doesn't check is_active)
        login = await client.post(
            "/api/auth/token",
            data={"username": "inactive_da", "password": "Active@Pass99"},
        )
        assert login.status_code == 200, "Login should succeed even for inactive user"
        token = login.json()["access_token"]

        # But /me must reject the token
        me = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me.status_code == 401
    finally:
        from sqlalchemy import select
        async with _TestSession() as session:
            result = await session.execute(select(User).where(User.id == uid))
            u = result.scalar_one_or_none()
            if u:
                await session.delete(u)
                await session.commit()


# ═══════════════════════════════════════════════════════════════════════
# 3. Token expiry
# ═══════════════════════════════════════════════════════════════════════

async def test_expired_token_is_401(
    client: AsyncClient, admin_user, make_expired_token
):
    """
    A JWT whose `exp` claim is in the past must be rejected with 401,
    even though the signature and payload are otherwise valid.
    """
    token = make_expired_token(admin_user.id, admin_user.role)
    resp = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


async def test_nearly_expired_token_still_works(
    client: AsyncClient, admin_user, make_token
):
    """
    A token with 1 minute remaining must still be accepted (boundary check).
    """
    token = make_token(admin_user.id, admin_user.role, expire_minutes=1)
    resp = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
