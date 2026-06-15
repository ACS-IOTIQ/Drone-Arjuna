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
