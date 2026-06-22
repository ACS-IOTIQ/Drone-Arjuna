"""
Drone Instances API tests
=========================
GET / POST / PUT / PATCH / DELETE /api/master/drones
GET /api/master/drones/{did}/type-spec

Covers:
  - Happy-path register / list / get / update / status patch / type-spec
  - Duplicate call_sign → 409
  - Duplicate serial_number → 409
  - Invalid drone_type_id → 404
  - Invalid status value → 400
  - RBAC: VIEWER blocked from writes; FLIGHT_CONTROLLER can patch status
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


_DT_BODY = {
    "name": "Inst-Test Hawk",
    "manufacturer": "Test Corp",
    "model": "Inst-Hawk-T",
    "size_class": "small",
    "mission_type": "ISR",
    "is_vtol": False,
    "max_speed_ms": 25.0,
    "cruise_speed_ms": 18.0,
    "max_altitude_m": 2000.0,
    "endurance_h": 2.0,
    "range_km": 40.0,
    "max_takeoff_weight_kg": 5.0,
    "max_payload_weight_kg": 1.0,
    "autopilot_type": "PX4",
}


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
        "call_sign":        "TEST-ALPHA-01",
        "drone_type_id":    drone_type["id"],
        "serial_number":    "SN-INST-001",
    }
    resp = await client.post("/api/master/drones", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/master/drones/{data['id']}", headers=hdrs)


# ══════════════════════════════════════════════════════════════════════
# Register (create)
# ══════════════════════════════════════════════════════════════════════

async def test_register_drone_201(
    client: AsyncClient, admin_user, drone_type, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    body  = {
        "call_sign":     "TEST-BRAVO-01",
        "drone_type_id": drone_type["id"],
        "serial_number": "SN-INST-002",
    }
    resp = await client.post("/api/master/drones", json=body, headers=hdrs)
    assert resp.status_code == 201
    data = resp.json()
    assert data["call_sign"]     == "TEST-BRAVO-01"   # validator uppercases
    assert data["drone_type_id"] == drone_type["id"]
    assert data["status"]        == "offline"
    assert "id" in data
    await client.delete(f"/api/master/drones/{data['id']}", headers=hdrs)


async def test_register_drone_duplicate_callsign_409(
    client: AsyncClient, admin_user, drone_instance, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    body  = {
        "call_sign":     drone_instance["call_sign"],  # same call_sign
        "drone_type_id": drone_instance["drone_type_id"],
        "serial_number": "SN-UNIQUE-999",
    }
    resp = await client.post(
        "/api/master/drones",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


async def test_register_drone_duplicate_serial_409(
    client: AsyncClient, admin_user, drone_instance, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    body  = {
        "call_sign":     "UNIQUE-SIGN-99",
        "drone_type_id": drone_instance["drone_type_id"],
        "serial_number": drone_instance["serial_number"],  # same serial
    }
    resp = await client.post(
        "/api/master/drones",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


async def test_register_drone_invalid_type_404(
    client: AsyncClient, admin_user, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    body  = {
        "call_sign":     "GHOST-01",
        "drone_type_id": 999999,
        "serial_number": "SN-GHOST-001",
    }
    resp = await client.post(
        "/api/master/drones",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# Read
# ══════════════════════════════════════════════════════════════════════

async def test_list_drones_200(
    client: AsyncClient, viewer_user, drone_instance, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/master/drones",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert drone_instance["id"] in [d["id"] for d in resp.json()]


async def test_get_drone_200(
    client: AsyncClient, viewer_user, drone_instance, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        f"/api/master/drones/{drone_instance['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["serial_number"] == drone_instance["serial_number"]


async def test_get_drone_not_found_404(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/master/drones/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# Update
# ══════════════════════════════════════════════════════════════════════

async def test_update_drone_notes_200(
    client: AsyncClient, admin_user, drone_instance, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.put(
        f"/api/master/drones/{drone_instance['id']}",
        json={"notes": "Updated in test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "Updated in test"


async def test_patch_drone_status_200(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """FLIGHT_CONTROLLER can update drone status."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.patch(
        f"/api/master/drones/{drone_instance['id']}/status",
        json={"status": "maintenance"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "maintenance"


async def test_patch_drone_status_invalid_400(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """Invalid status value must return 400."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.patch(
        f"/api/master/drones/{drone_instance['id']}/status",
        json={"status": "destroyed"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_patch_drone_status_viewer_403(
    client: AsyncClient, viewer_user, drone_instance, make_token
):
    """VIEWER cannot patch drone status."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.patch(
        f"/api/master/drones/{drone_instance['id']}/status",
        json={"status": "online"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# Type spec
# ══════════════════════════════════════════════════════════════════════

async def test_get_drone_type_spec_200(
    client: AsyncClient, viewer_user, drone_instance, drone_type, make_token
):
    """type-spec endpoint returns the full DroneType for the instance."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        f"/api/master/drones/{drone_instance['id']}/type-spec",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == drone_type["id"]


# ══════════════════════════════════════════════════════════════════════
# RBAC
# ══════════════════════════════════════════════════════════════════════

async def test_drones_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/master/drones")
    assert resp.status_code == 401


async def test_viewer_blocked_from_register_drone_403(
    client: AsyncClient, viewer_user, drone_type, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        "/api/master/drones",
        json={
            "call_sign":     "VIEWER-DRONE-99",
            "drone_type_id": drone_type["id"],
            "serial_number": "SN-VIEWER-99",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# DB Persistence — verify all fields round-trip through POST → GET
# ══════════════════════════════════════════════════════════════════════

async def test_drone_instance_all_fields_persisted(
    client: AsyncClient, admin_user, drone_type, make_token
):
    """Every field submitted on POST must be retrievable unchanged via GET."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    body  = {
        "call_sign":          "persist-test-01",   # validator uppercases this
        "drone_type_id":      drone_type["id"],
        "serial_number":      "PT-SN-2026-001",
        "mavlink_system_id":  5,
        "notes":              "db persistence check",
    }
    create = await client.post("/api/master/drones", json=body, headers=hdrs)
    assert create.status_code == 201
    did = create.json()["id"]
    try:
        get    = await client.get(f"/api/master/drones/{did}", headers=hdrs)
        assert get.status_code == 200
        stored = get.json()
        assert stored["call_sign"]         == "PERSIST-TEST-01"   # uppercased by validator
        assert stored["drone_type_id"]     == body["drone_type_id"]
        assert stored["serial_number"]     == body["serial_number"]
        assert stored["mavlink_system_id"] == body["mavlink_system_id"]
        assert stored["notes"]             == body["notes"]
        assert stored["status"]            == "available"          # default on creation
    finally:
        await client.delete(f"/api/master/drones/{did}", headers=hdrs)
