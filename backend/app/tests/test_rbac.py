"""
Role-Based Access Control (RBAC) tests
=======================================
Verifies that each endpoint enforces the correct minimum role.

Role hierarchy (lowest → highest):
    viewer < flight_controller < mission_commander < admin

Endpoints under test
--------------------
  GET  /api/drone-control/ports
       → minimum role: VIEWER (any authenticated user)

  POST /api/drone-control/autoconnect
       → minimum role: FLIGHT_CONTROLLER

  GET  /api/auth/users
       → admin-only (checked inline in the route, not via rbac.py)

  POST /api/auth/register
       → admin-only

Test matrix
-----------
  Endpoint                     | no auth | viewer | flight_ctrl | admin
  -----------------------------|---------|--------|-------------|-------
  GET  /ports                  |  401    |  200   |    200      |  200
  POST /autoconnect            |  401    |  403   |  not 403*   |  200
  GET  /auth/users             |  401    |  403   |    403      |  200
  POST /auth/register          |  401    |  403   |    403      |  201

  * The flight_controller role passes the auth check.  The request then hits
    the DB lookup and returns 404 (drone not found), confirming the role gate
    did NOT fire.
"""
import pytest
from httpx import AsyncClient


# ═══════════════════════════════════════════════════════════════════════
# GET /api/drone-control/ports
# ═══════════════════════════════════════════════════════════════════════

async def test_ports_unauthenticated_is_401(client: AsyncClient):
    """No auth header → 401 (OAuth2 bearer scheme rejects the request)."""
    resp = await client.get("/api/drone-control/ports")
    assert resp.status_code == 401


async def test_ports_viewer_is_200(client: AsyncClient, viewer_user, make_token):
    """
    VIEWER is the minimum required role for /ports.
    A VIEWER token must receive HTTP 200 and a list of port objects.
    """
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        "/api/drone-control/ports",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    ports = resp.json()
    assert isinstance(ports, list)
    # Hardcoded network endpoints are always present
    types = {p["type"] for p in ports}
    assert "udp" in types or "tcp" in types


async def test_ports_flight_controller_is_200(
    client: AsyncClient, flight_controller_user, make_token
):
    """FLIGHT_CONTROLLER role is above VIEWER — must also receive 200."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.get(
        "/api/drone-control/ports",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


async def test_ports_admin_is_200(client: AsyncClient, admin_user, make_token):
    """ADMIN is above all roles — must also receive 200 for /ports."""
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.get(
        "/api/drone-control/ports",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
# POST /api/drone-control/autoconnect  (min role: FLIGHT_CONTROLLER)
# ═══════════════════════════════════════════════════════════════════════

async def test_autoconnect_unauthenticated_is_401(client: AsyncClient):
    """No auth → 401 before the role check even fires."""
    resp = await client.post(
        "/api/drone-control/autoconnect",
        json={"drone_instance_id": 1},
    )
    assert resp.status_code == 401


async def test_autoconnect_viewer_is_403(
    client: AsyncClient, viewer_user, make_token
):
    """
    VIEWER role is below the FLIGHT_CONTROLLER minimum for /autoconnect.
    The require_min_role dependency must return 403 before touching the DB.
    """
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.post(
        "/api/drone-control/autoconnect",
        json={"drone_instance_id": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_autoconnect_flight_controller_passes_role_check(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    FLIGHT_CONTROLLER meets the minimum role for /autoconnect.
    The role gate must NOT return 403.
    The request proceeds to the DB lookup and returns 404 (no such drone),
    confirming the RBAC gate was cleared successfully.
    """
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.post(
        "/api/drone-control/autoconnect",
        json={"drone_instance_id": 999999},  # non-existent drone
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code != 403, (
        f"Expected role check to pass, but got 403. Body: {resp.text}"
    )
    assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# GET /api/auth/users  (admin-only)
# ═══════════════════════════════════════════════════════════════════════

async def test_list_users_unauthenticated_is_401(client: AsyncClient):
    resp = await client.get("/api/auth/users")
    assert resp.status_code == 401


async def test_list_users_viewer_is_403(
    client: AsyncClient, viewer_user, make_token
):
    """Non-admin roles must receive 403 for the user-list endpoint."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        "/api/auth/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_list_users_flight_controller_is_403(
    client: AsyncClient, flight_controller_user, make_token
):
    """Even FLIGHT_CONTROLLER is not permitted to list users."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.get(
        "/api/auth/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_list_users_admin_is_200(
    client: AsyncClient, admin_user, make_token
):
    """Admin must receive HTTP 200 and a JSON list."""
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.get(
        "/api/auth/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ═══════════════════════════════════════════════════════════════════════
# POST /api/auth/register  (admin-only)
# ═══════════════════════════════════════════════════════════════════════

_VALID_NEW_USER = {
    "username": "brand_new_pilot",
    "email": "brand_new_pilot@example.com",   # .local TLD fails EmailStr validation
    "password": "NewPilot@2099",              # passes PasswordPolicy
    "full_name": "Brand New Pilot",
    "role": "viewer",
}


async def test_register_unauthenticated_is_401(client: AsyncClient):
    resp = await client.post("/api/auth/register", json=_VALID_NEW_USER)
    assert resp.status_code == 401


async def test_register_viewer_is_403(
    client: AsyncClient, viewer_user, make_token
):
    """VIEWER must not be able to register new accounts."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.post(
        "/api/auth/register",
        json=_VALID_NEW_USER,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_register_flight_controller_is_403(
    client: AsyncClient, flight_controller_user, make_token
):
    """FLIGHT_CONTROLLER must not be able to register new accounts."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.post(
        "/api/auth/register",
        json=_VALID_NEW_USER,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_register_admin_creates_user_201(
    client: AsyncClient, admin_user, make_token
):
    """
    Admin must be able to create a new user.
    The response must be HTTP 201 and include the new user's username.
    The created user is cleaned up at the end of the test.
    """
    from app.models.user import User
    from app.tests.conftest import _TestSession
    from sqlalchemy import select

    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        "/api/auth/register",
        json=_VALID_NEW_USER,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "brand_new_pilot"
    assert body["role"] == "viewer"
    assert body["is_active"] is True

    # Cleanup: remove the created user so the test leaves no residue
    async with _TestSession() as session:
        result = await session.execute(
            select(User).where(User.username == "brand_new_pilot")
        )
        created = result.scalar_one_or_none()
        if created:
            await session.delete(created)
            await session.commit()
