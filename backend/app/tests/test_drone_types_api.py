"""
Drone Types API tests
=====================
GET / POST / PUT / DELETE /api/master/drone-types
GET /api/master/drone-types/stats

Covers:
  - Happy-path create / list / get / update / archive
  - Duplicate name → 409
  - cruise_speed_ms > max_speed_ms → 422 (schema validator)
  - Archive blocked while drone instance references the type → 409
  - Archived type no longer appears in list or GET → 404
  - RBAC: VIEWER blocked from all write operations
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


_DT_BODY = {
    "name": "Test Hawk-200",
    "manufacturer": "Test Systems Ltd",
    "model": "Hawk-200-T",
    "size_class": "medium",
    "mission_type": "ISR",
    "is_vtol": True,
    "max_speed_ms": 30.0,
    "cruise_speed_ms": 20.0,
    "max_altitude_m": 3000.0,
    "endurance_h": 4.0,
    "range_km": 80.0,
    "max_takeoff_weight_kg": 15.0,
    "max_payload_weight_kg": 3.0,
    "autopilot_type": "ArduPilot",
}

_DT_BODY2 = {**_DT_BODY, "name": "Test Falcon-100", "model": "Falcon-100-T"}


@pytest_asyncio.fixture
async def drone_type(client: AsyncClient, admin_user, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.post("/api/master/drone-types", json=_DT_BODY, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data  = resp.json()
    yield data
    await client.delete(f"/api/master/drone-types/{data['id']}", headers=hdrs)


# ══════════════════════════════════════════════════════════════════════
# Create
# ══════════════════════════════════════════════════════════════════════

async def test_create_drone_type_201(client: AsyncClient, admin_user, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.post("/api/master/drone-types", json=_DT_BODY2, headers=hdrs)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"]       == _DT_BODY2["name"]
    assert body["size_class"] == "medium"
    assert body["is_active"]  is True
    assert "id"         in body
    assert "created_at" in body
    await client.delete(f"/api/master/drone-types/{body['id']}", headers=hdrs)


async def test_create_drone_type_duplicate_name_409(
    client: AsyncClient, admin_user, drone_type, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.post(
        "/api/master/drone-types",
        json=_DT_BODY,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


async def test_create_drone_type_cruise_exceeds_max_422(
    client: AsyncClient, admin_user, make_token
):
    """cruise_speed_ms > max_speed_ms must be rejected by the schema validator."""
    token = make_token(admin_user.id, admin_user.role)
    bad   = {**_DT_BODY, "name": "Bad Speed Drone",
             "max_speed_ms": 20.0, "cruise_speed_ms": 25.0}
    resp  = await client.post(
        "/api/master/drone-types",
        json=bad,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_create_drone_type_payload_exceeds_mtow_422(
    client: AsyncClient, admin_user, make_token
):
    """max_payload_weight_kg > max_takeoff_weight_kg must be rejected → 422."""
    token = make_token(admin_user.id, admin_user.role)
    bad   = {**_DT_BODY, "name": "Bad Payload Drone",
             "max_takeoff_weight_kg": 10.0, "max_payload_weight_kg": 12.0}
    resp  = await client.post(
        "/api/master/drone-types",
        json=bad,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_create_drone_type_payload_equals_mtow_422(
    client: AsyncClient, admin_user, make_token
):
    """max_payload_weight_kg == max_takeoff_weight_kg must also be rejected → 422."""
    token = make_token(admin_user.id, admin_user.role)
    bad   = {**_DT_BODY, "name": "Equal Weight Drone",
             "max_takeoff_weight_kg": 10.0, "max_payload_weight_kg": 10.0}
    resp  = await client.post(
        "/api/master/drone-types",
        json=bad,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# Read
# ══════════════════════════════════════════════════════════════════════

async def test_list_drone_types_200(
    client: AsyncClient, viewer_user, drone_type, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/master/drone-types",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert drone_type["id"] in [item["id"] for item in resp.json()]


async def test_get_drone_type_200(
    client: AsyncClient, viewer_user, drone_type, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        f"/api/master/drone-types/{drone_type['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == _DT_BODY["name"]


async def test_get_drone_type_not_found_404(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/master/drone-types/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_drone_type_stats_200(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/master/drone-types/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "total_active_types" in body
    assert "by_size_class"      in body


# ══════════════════════════════════════════════════════════════════════
# Update
# ══════════════════════════════════════════════════════════════════════

async def test_update_drone_type_notes_200(
    client: AsyncClient, admin_user, drone_type, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.put(
        f"/api/master/drone-types/{drone_type['id']}",
        json={"notes": "Updated in test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "Updated in test"


async def test_update_drone_type_not_found_404(
    client: AsyncClient, admin_user, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.put(
        "/api/master/drone-types/999999",
        json={"notes": "Should 404"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# Archive (soft-delete)
# ══════════════════════════════════════════════════════════════════════

async def test_archive_drone_type_204(client: AsyncClient, admin_user, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    create = await client.post(
        "/api/master/drone-types",
        json={**_DT_BODY, "name": "Temporary Type"},
        headers=hdrs,
    )
    assert create.status_code == 201
    tid = create.json()["id"]

    delete = await client.delete(f"/api/master/drone-types/{tid}", headers=hdrs)
    assert delete.status_code == 204

    # Archived type is no longer visible
    get = await client.get(f"/api/master/drone-types/{tid}", headers=hdrs)
    assert get.status_code == 404


async def test_archive_drone_type_blocked_by_instance_409(
    client: AsyncClient, admin_user, drone_type, make_token
):
    """Cannot archive a type while a DroneInstance still references it."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}

    # Register an instance referencing this type
    inst_resp = await client.post(
        "/api/master/drones",
        json={
            "call_sign": "BLOCK-TEST-01",
            "drone_type_id": drone_type["id"],
            "serial_number": "BLOCK-SN-001",
        },
        headers=hdrs,
    )
    assert inst_resp.status_code == 201

    # Attempt to archive the type — must be blocked
    resp = await client.delete(
        f"/api/master/drone-types/{drone_type['id']}", headers=hdrs
    )
    assert resp.status_code == 409

    # Cleanup the instance
    await client.delete(
        f"/api/master/drones/{inst_resp.json()['id']}", headers=hdrs
    )


# ══════════════════════════════════════════════════════════════════════
# RBAC
# ══════════════════════════════════════════════════════════════════════

async def test_drone_types_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/master/drone-types")
    assert resp.status_code == 401


async def test_viewer_blocked_from_create_drone_type_403(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        "/api/master/drone-types",
        json=_DT_BODY,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_viewer_blocked_from_update_drone_type_403(
    client: AsyncClient, viewer_user, drone_type, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.put(
        f"/api/master/drone-types/{drone_type['id']}",
        json={"notes": "Should fail"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_viewer_blocked_from_archive_drone_type_403(
    client: AsyncClient, viewer_user, drone_type, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.delete(
        f"/api/master/drone-types/{drone_type['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# DB Persistence — verify all fields round-trip through POST → GET
# ══════════════════════════════════════════════════════════════════════

async def test_drone_type_all_fields_persisted(
    client: AsyncClient, admin_user, make_token
):
    """Every field submitted on POST must be retrievable unchanged via GET."""
    token  = make_token(admin_user.id, admin_user.role)
    hdrs   = {"Authorization": f"Bearer {token}"}
    body   = {
        "name":                   "Persist-Test Eagle",
        "manufacturer":           "ACS Systems",
        "model":                  "Eagle-PT-1",
        "size_class":             "large",
        "mission_type":           "Strike",
        "is_vtol":                False,
        "max_speed_ms":           50.0,
        "cruise_speed_ms":        35.0,
        "max_altitude_m":         5000.0,
        "endurance_h":            6.0,
        "range_km":               150.0,
        "max_takeoff_weight_kg":  25.0,
        "max_payload_weight_kg":  8.0,
        "autopilot_type":         "PX4",
        "notes":                  "persistence check",
    }
    create = await client.post("/api/master/drone-types", json=body, headers=hdrs)
    assert create.status_code == 201
    tid = create.json()["id"]
    try:
        get  = await client.get(f"/api/master/drone-types/{tid}", headers=hdrs)
        assert get.status_code == 200
        stored = get.json()
        assert stored["name"]                   == body["name"]
        assert stored["manufacturer"]           == body["manufacturer"]
        assert stored["model"]                  == body["model"]
        assert stored["size_class"]             == body["size_class"]
        assert stored["mission_type"]           == body["mission_type"]
        assert stored["is_vtol"]                == body["is_vtol"]
        assert stored["max_speed_ms"]           == body["max_speed_ms"]
        assert stored["cruise_speed_ms"]        == body["cruise_speed_ms"]
        assert stored["max_altitude_m"]         == body["max_altitude_m"]
        assert stored["endurance_h"]            == body["endurance_h"]
        assert stored["range_km"]               == body["range_km"]
        assert stored["max_takeoff_weight_kg"]  == body["max_takeoff_weight_kg"]
        assert stored["max_payload_weight_kg"]  == body["max_payload_weight_kg"]
        assert stored["autopilot_type"]         == body["autopilot_type"]
        assert stored["notes"]                  == body["notes"]
    finally:
        await client.delete(f"/api/master/drone-types/{tid}", headers=hdrs)
