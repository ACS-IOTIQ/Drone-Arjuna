"""
Naval Vessels API tests
=======================
GET / POST / PUT / DELETE /api/master/vessels
POST /api/master/vessels/{vid}/position
POST /api/master/vessels/{vid}/assign-drone/{did}
POST /api/master/vessels/{vid}/unassign-drone/{did}

Covers:
  - Happy-path create / list / get / update / archive
  - Duplicate vessel_id → 409
  - vessel_id is forced to uppercase
  - Archive blocked while a drone is assigned → 409
  - Position update via POST
  - Drone assign / unassign
  - RBAC: VIEWER blocked from all write operations
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


_VESSEL_BODY = {
    "vessel_id":    "TEST-V01",
    "name":         "INS Test Vessel One",
    "vessel_type":  "corvette",
    "landing_spots": 2,
}

_VESSEL_BODY2 = {**_VESSEL_BODY, "vessel_id": "TEST-V02", "name": "INS Test Vessel Two"}

_DT_BODY = {
    "name": "Vessel-Test Hawk",
    "manufacturer": "Test Corp",
    "model": "V-Hawk-T",
    "size_class": "small",
    "mission_type": "ISR",
    "is_vtol": True,
    "max_speed_ms": 20.0,
    "cruise_speed_ms": 15.0,
    "max_altitude_m": 1500.0,
    "endurance_h": 1.5,
    "range_km": 30.0,
    "max_takeoff_weight_kg": 4.0,
    "max_payload_weight_kg": 0.8,
    "autopilot_type": "ArduPilot",
}


@pytest_asyncio.fixture
async def vessel(client: AsyncClient, admin_user, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.post("/api/master/vessels", json=_VESSEL_BODY, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data  = resp.json()
    yield data
    await client.delete(f"/api/master/vessels/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def drone_type(client: AsyncClient, admin_user, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.post("/api/master/drone-types", json=_DT_BODY, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data  = resp.json()
    yield data
    await client.delete(f"/api/master/drone-types/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def drone_instance(client: AsyncClient, admin_user, drone_type, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    body  = {
        "call_sign":     "VESSEL-DRONE-01",
        "drone_type_id": drone_type["id"],
        "serial_number": "SN-VESSEL-001",
    }
    resp = await client.post("/api/master/drones", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/master/drones/{data['id']}", headers=hdrs)


# ══════════════════════════════════════════════════════════════════════
# Create
# ══════════════════════════════════════════════════════════════════════

async def test_create_vessel_201(client: AsyncClient, admin_user, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.post("/api/master/vessels", json=_VESSEL_BODY2, headers=hdrs)
    assert resp.status_code == 201
    body  = resp.json()
    assert body["vessel_id"]   == "TEST-V02"      # forced uppercase
    assert body["vessel_type"] == "corvette"
    assert body["is_active"]   is True
    assert "id"         in body
    assert "created_at" in body
    await client.delete(f"/api/master/vessels/{body['id']}", headers=hdrs)


async def test_create_vessel_uppercases_id(client: AsyncClient, admin_user, make_token):
    """vessel_id is always stored and returned as uppercase."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.post(
        "/api/master/vessels",
        json={**_VESSEL_BODY2, "vessel_id": "lowercase-v99"},
        headers=hdrs,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["vessel_id"] == "LOWERCASE-V99"
    await client.delete(f"/api/master/vessels/{body['id']}", headers=hdrs)


async def test_create_vessel_duplicate_id_409(
    client: AsyncClient, admin_user, vessel, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.post(
        "/api/master/vessels",
        json={**_VESSEL_BODY, "vessel_id": _VESSEL_BODY["vessel_id"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


# ══════════════════════════════════════════════════════════════════════
# Read
# ══════════════════════════════════════════════════════════════════════

async def test_list_vessels_200(
    client: AsyncClient, viewer_user, vessel, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/master/vessels",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert vessel["id"] in [v["id"] for v in resp.json()]


async def test_get_vessel_200(
    client: AsyncClient, viewer_user, vessel, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        f"/api/master/vessels/{vessel['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["vessel_id"] == _VESSEL_BODY["vessel_id"]


async def test_get_vessel_not_found_404(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/master/vessels/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# Update / position
# ══════════════════════════════════════════════════════════════════════

async def test_update_vessel_200(
    client: AsyncClient, admin_user, vessel, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.put(
        f"/api/master/vessels/{vessel['id']}",
        json={"notes": "Updated in test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "Updated in test"


async def test_update_vessel_position_200(
    client: AsyncClient, flight_controller_user, vessel, make_token
):
    """FLIGHT_CONTROLLER can push a GPS position update."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.post(
        f"/api/master/vessels/{vessel['id']}/position",
        json={"latitude": 15.5, "longitude": 73.8, "heading_deg": 45.0, "speed_kts": 12.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["latitude"]    == 15.5
    assert body["longitude"]   == 73.8
    assert body["heading_deg"] == 45.0


async def test_update_vessel_position_invalid_lat_422(
    client: AsyncClient, flight_controller_user, vessel, make_token
):
    """Latitude outside ±90 must be rejected."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.post(
        f"/api/master/vessels/{vessel['id']}/position",
        json={"latitude": 95.0, "longitude": 73.8},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# Drone assign / unassign
# ══════════════════════════════════════════════════════════════════════

async def test_assign_drone_to_vessel_200(
    client: AsyncClient, admin_user, vessel, drone_instance, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.post(
        f"/api/master/vessels/{vessel['id']}/assign-drone/{drone_instance['id']}",
        headers=hdrs,
    )
    assert resp.status_code == 200
    # Unassign after test
    await client.post(
        f"/api/master/vessels/{vessel['id']}/unassign-drone/{drone_instance['id']}",
        headers=hdrs,
    )


async def test_unassign_drone_from_vessel_200(
    client: AsyncClient, admin_user, vessel, drone_instance, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    # First assign
    await client.post(
        f"/api/master/vessels/{vessel['id']}/assign-drone/{drone_instance['id']}",
        headers=hdrs,
    )
    # Then unassign
    resp = await client.post(
        f"/api/master/vessels/{vessel['id']}/unassign-drone/{drone_instance['id']}",
        headers=hdrs,
    )
    assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════
# Archive (soft-delete)
# ══════════════════════════════════════════════════════════════════════

async def test_archive_vessel_204(client: AsyncClient, admin_user, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    create = await client.post(
        "/api/master/vessels",
        json={**_VESSEL_BODY, "vessel_id": "ARCHIVE-ME-01"},
        headers=hdrs,
    )
    assert create.status_code == 201
    vid = create.json()["id"]

    delete = await client.delete(f"/api/master/vessels/{vid}", headers=hdrs)
    assert delete.status_code == 204

    get = await client.get(f"/api/master/vessels/{vid}", headers=hdrs)
    assert get.status_code == 404


async def test_archive_vessel_blocked_by_drone_409(
    client: AsyncClient, admin_user, vessel, drone_instance, make_token
):
    """Cannot archive vessel while a drone is assigned to it."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}

    # Assign drone to vessel
    await client.post(
        f"/api/master/vessels/{vessel['id']}/assign-drone/{drone_instance['id']}",
        headers=hdrs,
    )
    # Try to archive — must be blocked
    resp = await client.delete(f"/api/master/vessels/{vessel['id']}", headers=hdrs)
    assert resp.status_code == 409

    # Cleanup: unassign drone so fixture teardown can delete the vessel
    await client.post(
        f"/api/master/vessels/{vessel['id']}/unassign-drone/{drone_instance['id']}",
        headers=hdrs,
    )


# ══════════════════════════════════════════════════════════════════════
# RBAC
# ══════════════════════════════════════════════════════════════════════

async def test_vessels_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/master/vessels")
    assert resp.status_code == 401


async def test_viewer_blocked_from_create_vessel_403(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        "/api/master/vessels",
        json=_VESSEL_BODY,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_viewer_blocked_from_archive_vessel_403(
    client: AsyncClient, viewer_user, vessel, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.delete(
        f"/api/master/vessels/{vessel['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_viewer_blocked_from_position_update_403(
    client: AsyncClient, viewer_user, vessel, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        f"/api/master/vessels/{vessel['id']}/position",
        json={"latitude": 15.0, "longitude": 73.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
