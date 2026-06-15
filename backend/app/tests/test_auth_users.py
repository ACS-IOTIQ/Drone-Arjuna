"""
Auth — /register and /users endpoint tests
===========================================
POST /api/auth/register
GET  /api/auth/users

Covers:
  - Admin can register a new user with valid credentials → 201
  - Registered user can immediately log in
  - Duplicate username → 409
  - Weak password (too short, no uppercase, no digit, no special char) → 422
  - Username with spaces → 422
  - Invalid role value → 422
  - Non-admin trying to register → 403
  - Admin can list all users → 200
  - Non-admin cannot list users → 403
  - Unauthenticated access → 401
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


_VALID_NEW_USER = {
    "username": "newpilot",
    "email": "newpilot@example.com",  # .local TLD fails Pydantic EmailStr
    "password": "Pilot@Secure99",
    "full_name": "New Pilot",
    "role": "flight_controller",
}


# ══════════════════════════════════════════════════════════════════════
# Register — happy path
# ══════════════════════════════════════════════════════════════════════

async def test_register_user_201(client: AsyncClient, admin_user, make_token):
    """Admin can create a new user; response has required fields."""
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        "/api/auth/register",
        json=_VALID_NEW_USER,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "newpilot"
    assert body["role"] == "flight_controller"
    assert body["is_active"] is True
    assert "id" in body
    assert "created_at" in body
    # Password must NOT be returned
    assert "password" not in body
    assert "hashed_password" not in body


async def test_registered_user_can_login(client: AsyncClient, admin_user, make_token):
    """A newly-registered user can immediately authenticate."""
    token = make_token(admin_user.id, admin_user.role)
    await client.post(
        "/api/auth/register",
        json=_VALID_NEW_USER,
        headers={"Authorization": f"Bearer {token}"},
    )
    login = await client.post(
        "/api/auth/token",
        data={"username": "newpilot", "password": "Pilot@Secure99"},
    )
    assert login.status_code == 200
    assert login.json()["role"] == "flight_controller"


async def test_register_viewer_role_201(client: AsyncClient, admin_user, make_token):
    """Admin can register a viewer-role account."""
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        "/api/auth/register",
        json={
            "username": "observer01",
            "email": "observer01@example.com",  # .local TLD fails EmailStr
            "password": "Observe@Secure99",
            "role": "viewer",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "viewer"


# ══════════════════════════════════════════════════════════════════════
# Register — conflict
# ══════════════════════════════════════════════════════════════════════

async def test_register_duplicate_username_409(
    client: AsyncClient, admin_user, make_token
):
    """Registering the same username twice must return 409."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}

    first = await client.post("/api/auth/register", json=_VALID_NEW_USER, headers=hdrs)
    assert first.status_code == 201

    second = await client.post("/api/auth/register", json=_VALID_NEW_USER, headers=hdrs)
    assert second.status_code == 409


# ══════════════════════════════════════════════════════════════════════
# Register — password policy
# ══════════════════════════════════════════════════════════════════════

async def test_register_weak_password_too_short_422(
    client: AsyncClient, admin_user, make_token
):
    """Password shorter than 10 characters must be rejected with 422."""
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        "/api/auth/register",
        json={**_VALID_NEW_USER, "username": "weakuser1", "password": "Ab1!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_register_weak_password_no_uppercase_422(
    client: AsyncClient, admin_user, make_token
):
    """Password without an uppercase letter must be rejected."""
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        "/api/auth/register",
        json={**_VALID_NEW_USER, "username": "weakuser2", "password": "alllower@1234"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_register_weak_password_no_digit_422(
    client: AsyncClient, admin_user, make_token
):
    """Password without a digit must be rejected."""
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        "/api/auth/register",
        json={**_VALID_NEW_USER, "username": "weakuser3", "password": "NoDigitPass@"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_register_weak_password_no_special_char_422(
    client: AsyncClient, admin_user, make_token
):
    """Password without a special character must be rejected."""
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        "/api/auth/register",
        json={**_VALID_NEW_USER, "username": "weakuser4", "password": "NoSpecial1234A"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# Register — schema validation
# ══════════════════════════════════════════════════════════════════════

async def test_register_username_with_spaces_422(
    client: AsyncClient, admin_user, make_token
):
    """Username must not contain spaces."""
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        "/api/auth/register",
        json={**_VALID_NEW_USER, "username": "bad user name", "password": "Valid@Pass99"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_register_invalid_role_422(
    client: AsyncClient, admin_user, make_token
):
    """An invalid role value must be rejected by the schema validator."""
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        "/api/auth/register",
        json={**_VALID_NEW_USER, "username": "badroleuser", "role": "god_mode"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_register_invalid_email_422(
    client: AsyncClient, admin_user, make_token
):
    """An invalid email address must be rejected."""
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        "/api/auth/register",
        json={**_VALID_NEW_USER, "username": "bademailuser", "email": "not-an-email"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# Register — RBAC
# ══════════════════════════════════════════════════════════════════════

async def test_register_non_admin_403(
    client: AsyncClient, flight_controller_user, make_token
):
    """Non-admin cannot register new users."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.post(
        "/api/auth/register",
        json=_VALID_NEW_USER,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_register_viewer_403(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.post(
        "/api/auth/register",
        json=_VALID_NEW_USER,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_register_unauthenticated_401(client: AsyncClient):
    resp = await client.post("/api/auth/register", json=_VALID_NEW_USER)
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# List users
# ══════════════════════════════════════════════════════════════════════

async def test_list_users_admin_200(client: AsyncClient, admin_user, make_token):
    """Admin can list all users; the test admin appears in the result."""
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.get(
        "/api/auth/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    users = resp.json()
    assert isinstance(users, list)
    assert len(users) >= 1
    ids = [u["id"] for u in users]
    assert admin_user.id in ids
    # Passwords must not be exposed
    for u in users:
        assert "hashed_password" not in u
        assert "password" not in u


async def test_list_users_non_admin_403(
    client: AsyncClient, flight_controller_user, make_token
):
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.get(
        "/api/auth/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_list_users_viewer_403(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        "/api/auth/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_list_users_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/auth/users")
    assert resp.status_code == 401
