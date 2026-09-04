"""
Gap-fill tests for app.core.auth endpoints not covered by test_auth.py,
test_access_requests_api.py, or test_approve_reject_workflow.py:

  - POST /api/auth/register        happy path, viewer-forbidden, unauthenticated
  - GET  /api/auth/users           happy path (list), viewer-forbidden, unauthenticated
  - POST /api/auth/refresh         happy path, wrong token type, invalid token, inactive user
  - POST /api/auth/forgot-password unknown email, inactive user, SMTP disabled, happy path
  - POST /api/auth/reset-password  invalid token, expired token, happy path
"""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from jose import jwt

from app.config import get_settings

cfg = get_settings()


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ══════════════════════════════════════════════════════════════════════
# POST /register
# ══════════════════════════════════════════════════════════════════════

async def test_register_happy_path_201(client: AsyncClient, admin_user, make_token):
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        "/api/auth/register",
        json={
            "username": "brand_new_user",
            "email": "brand_new_user@example.com",
            "password": "Unique@Pass99",
            "role": "viewer",
            "full_name": "Brand New",
        },
        headers=_bearer(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["username"] == "brand_new_user"
    assert body["role"] == "viewer"


async def test_register_viewer_forbidden_403(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.post(
        "/api/auth/register",
        json={
            "username": "someone_else",
            "email": "someone_else@example.com",
            "password": "Unique@Pass99",
            "role": "viewer",
        },
        headers=_bearer(token),
    )
    assert resp.status_code == 403


async def test_register_unauthenticated_401(client: AsyncClient):
    resp = await client.post(
        "/api/auth/register",
        json={
            "username": "x",
            "email": "x@example.com",
            "password": "Unique@Pass99",
        },
    )
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# GET /users
# ══════════════════════════════════════════════════════════════════════

async def test_list_users_admin_200(client: AsyncClient, admin_user, make_token):
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.get("/api/auth/users", headers=_bearer(token))
    assert resp.status_code == 200
    usernames = [u["username"] for u in resp.json()]
    assert admin_user.username in usernames


async def test_list_users_viewer_forbidden_403(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get("/api/auth/users", headers=_bearer(token))
    assert resp.status_code == 403


async def test_list_users_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/auth/users")
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# POST /refresh
# ══════════════════════════════════════════════════════════════════════

async def test_refresh_returns_new_access_token(client: AsyncClient, admin_user):
    login_resp = await client.post(
        "/api/auth/token",
        data={"username": "admin_test", "password": "Admin@1234"},
    )
    refresh_token = login_resp.json()["refresh_token"]

    resp = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_refresh_rejects_access_token_used_as_refresh(client: AsyncClient, admin_user):
    login_resp = await client.post(
        "/api/auth/token",
        data={"username": "admin_test", "password": "Admin@1234"},
    )
    access_token = login_resp.json()["access_token"]

    resp = await client.post("/api/auth/refresh", json={"refresh_token": access_token})
    assert resp.status_code == 401


async def test_refresh_rejects_malformed_token(client: AsyncClient):
    resp = await client.post("/api/auth/refresh", json={"refresh_token": "not-a-jwt"})
    assert resp.status_code == 401


async def test_refresh_rejects_inactive_user(client: AsyncClient, admin_user):
    payload = {
        "sub": str(admin_user.id),
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=1),
    }
    refresh_token = jwt.encode(payload, cfg.secret_key, algorithm=cfg.algorithm)

    from app.tests.conftest import _TestSession
    from app.models.user import User
    from sqlalchemy import select

    async with _TestSession() as session:
        result = await session.execute(select(User).where(User.id == admin_user.id))
        u = result.scalar_one()
        u.is_active = False
        await session.commit()

    resp = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# POST /forgot-password
# ══════════════════════════════════════════════════════════════════════

async def test_forgot_password_unknown_email_returns_generic_message(client: AsyncClient):
    resp = await client.post("/api/auth/forgot-password", json={"email": "ghost@example.com"})
    assert resp.status_code == 200
    assert "registered" in resp.json()["message"].lower()


async def test_forgot_password_known_email_smtp_disabled_returns_generic_message(
    client: AsyncClient, admin_user, monkeypatch
):
    """SMTP is disabled in the test environment, so no reset token should be issued."""
    resp = await client.post("/api/auth/forgot-password", json={"email": admin_user.email})
    assert resp.status_code == 200
    assert "registered" in resp.json()["message"].lower()

    from app.tests.conftest import _TestSession
    from app.models.user import User
    from sqlalchemy import select

    async with _TestSession() as session:
        result = await session.execute(select(User).where(User.id == admin_user.id))
        u = result.scalar_one()
        assert u.reset_token is None


async def test_forgot_password_smtp_enabled_issues_reset_token(client: AsyncClient, admin_user):
    from app.core import auth as auth_module

    monkey_cfg = auth_module.cfg
    original = monkey_cfg.smtp_enabled
    monkey_cfg.smtp_enabled = True
    try:
        resp = await client.post("/api/auth/forgot-password", json={"email": admin_user.email})
    finally:
        monkey_cfg.smtp_enabled = original

    assert resp.status_code == 200

    from app.tests.conftest import _TestSession
    from app.models.user import User
    from sqlalchemy import select

    async with _TestSession() as session:
        result = await session.execute(select(User).where(User.id == admin_user.id))
        u = result.scalar_one()
        assert u.reset_token is not None
        assert u.reset_token_expires is not None


# ══════════════════════════════════════════════════════════════════════
# POST /reset-password
# ══════════════════════════════════════════════════════════════════════

async def test_reset_password_invalid_token_400(client: AsyncClient):
    resp = await client.post(
        "/api/auth/reset-password",
        json={"token": "not-a-real-token", "new_password": "NewPass@9999"},
    )
    assert resp.status_code == 400


async def test_reset_password_expired_token_400(client: AsyncClient, admin_user):
    from app.tests.conftest import _TestSession
    from app.models.user import User
    from sqlalchemy import select

    async with _TestSession() as session:
        result = await session.execute(select(User).where(User.id == admin_user.id))
        u = result.scalar_one()
        u.reset_token = "expired-token-123"
        u.reset_token_expires = datetime.now(timezone.utc) - timedelta(minutes=1)
        await session.commit()

    resp = await client.post(
        "/api/auth/reset-password",
        json={"token": "expired-token-123", "new_password": "NewPass@9999"},
    )
    assert resp.status_code == 400


async def test_reset_password_happy_path_updates_credentials(client: AsyncClient, admin_user):
    from app.tests.conftest import _TestSession
    from app.models.user import User
    from sqlalchemy import select

    async with _TestSession() as session:
        result = await session.execute(select(User).where(User.id == admin_user.id))
        u = result.scalar_one()
        u.reset_token = "valid-token-123"
        u.reset_token_expires = datetime.now(timezone.utc) + timedelta(minutes=30)
        await session.commit()

    resp = await client.post(
        "/api/auth/reset-password",
        json={"token": "valid-token-123", "new_password": "BrandNewPass@99"},
    )
    assert resp.status_code == 200

    login_resp = await client.post(
        "/api/auth/token",
        data={"username": "admin_test", "password": "BrandNewPass@99"},
    )
    assert login_resp.status_code == 200
