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
    assert data["created_at"] is not None
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
        assert stored["status"]            == "offline"            # default on creation
    finally:
        await client.delete(f"/api/master/drones/{did}", headers=hdrs)


# ══════════════════════════════════════════════════════════════════════
# Remove (soft-delete) — unassigns referencing missions rather than blocking
# ══════════════════════════════════════════════════════════════════════

async def test_remove_drone_no_missions_200(
    client: AsyncClient, admin_user, drone_instance, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.delete(f"/api/master/drones/{drone_instance['id']}", headers=hdrs)
    assert resp.status_code == 200, resp.text
    assert resp.json()["unassigned_missions"] == 0

    # No longer listed
    listing = await client.get("/api/master/drones", headers=hdrs)
    assert drone_instance["id"] not in [d["id"] for d in listing.json()]


async def test_recent_drone_cannot_be_removed_from_fleet_overview(
    client: AsyncClient, admin_user, drone_instance, make_token
):
    """The Fleet Overview cleanup route enforces the 30-day inactivity rule."""
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.delete(
        f"/api/master/drones/{drone_instance['id']}/stale",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert "30 days" in resp.json()["detail"]


async def test_stale_drone_can_be_removed_from_fleet_overview(
    client: AsyncClient, admin_user, drone_instance, make_token, monkeypatch
):
    """An eligible stale row is soft-removed and disappears from listings."""
    from app.modules.drone_master.service import DroneInstanceService

    monkeypatch.setattr(DroneInstanceService, "STALE_AFTER_DAYS", 0)
    token = make_token(admin_user.id, admin_user.role)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.delete(
        f"/api/master/drones/{drone_instance['id']}/stale",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    listing = await client.get("/api/master/drones", headers=headers)
    assert drone_instance["id"] not in [d["id"] for d in listing.json()]


async def test_remove_drone_unassigns_referencing_missions(
    client: AsyncClient, admin_user, drone_instance, make_token
):
    """Removing a drone that a mission points to must detach the mission
    (drone_instance_id -> null), not block removal or delete the mission."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}

    mission_resp = await client.post(
        "/api/flight/missions",
        json={
            "name": "Unassign-Test", "mission_type": "ISR",
            "drone_instance_id": drone_instance["id"], "waypoints": [],
        },
        headers=hdrs,
    )
    assert mission_resp.status_code == 201, mission_resp.text
    mission_id = mission_resp.json()["id"]

    resp = await client.delete(f"/api/master/drones/{drone_instance['id']}", headers=hdrs)
    assert resp.status_code == 200, resp.text
    assert resp.json()["unassigned_missions"] == 1

    mission_after = await client.get(f"/api/flight/missions/{mission_id}", headers=hdrs)
    assert mission_after.status_code == 200
    assert mission_after.json()["drone_instance_id"] is None


async def test_delete_drone_not_found_404(
    client: AsyncClient, admin_user, make_token
):
    """DELETE on a non-existent drone ID must return 404."""
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.delete(
        "/api/master/drones/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_delete_drone_viewer_403(
    client: AsyncClient, viewer_user, drone_instance, make_token
):
    """VIEWER role must not be able to delete a drone instance → 403."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.delete(
        f"/api/master/drones/{drone_instance['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# POST /api/master/drones/{did}/payload — Assign / clear payload
# ══════════════════════════════════════════════════════════════════════

_PT_BODY = {
    "name":         "Test EO Camera",
    "manufacturer": "ACS Optics",
    "model":        "EO-T01",
    "category":     "sensor",
}


async def test_assign_payload_to_drone_200_with_admin(
    client: AsyncClient, admin_user, flight_controller_user, drone_instance, make_token
):
    """
    Full round-trip: admin creates a payload type, flight_controller assigns it
    to a drone, then clears it — verifies assign and clear both persist.
    """
    admin_hdrs = {"Authorization": f"Bearer {make_token(admin_user.id, admin_user.role)}"}
    fc_hdrs    = {"Authorization": f"Bearer {make_token(flight_controller_user.id, flight_controller_user.role)}"}

    # Admin creates payload type
    pt_resp = await client.post("/api/master/payload-types", json=_PT_BODY, headers=admin_hdrs)
    assert pt_resp.status_code == 201, pt_resp.text
    pt_id = pt_resp.json()["id"]

    try:
        # Flight controller assigns it
        assign = await client.post(
            f"/api/master/drones/{drone_instance['id']}/payload",
            json={"payload_type_id": pt_id},
            headers=fc_hdrs,
        )
        assert assign.status_code == 200, assign.text
        assert assign.json()["payload_type_id"] == pt_id

        # Re-fetch confirms persistence
        get = await client.get(f"/api/master/drones/{drone_instance['id']}", headers=fc_hdrs)
        assert get.json()["payload_type_id"] == pt_id

        # Clear the payload
        clear = await client.post(
            f"/api/master/drones/{drone_instance['id']}/payload",
            json={"payload_type_id": None},
            headers=fc_hdrs,
        )
        assert clear.status_code == 200
        assert clear.json()["payload_type_id"] is None

        # Re-fetch confirms cleared
        get2 = await client.get(f"/api/master/drones/{drone_instance['id']}", headers=fc_hdrs)
        assert get2.json()["payload_type_id"] is None

    finally:
        await client.delete(f"/api/master/payload-types/{pt_id}", headers=admin_hdrs)


async def test_assign_payload_nonexistent_type_404(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """Assigning a non-existent payload_type_id must return 404."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.post(
        f"/api/master/drones/{drone_instance['id']}/payload",
        json={"payload_type_id": 999999},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_assign_payload_drone_not_found_404(
    client: AsyncClient, flight_controller_user, make_token
):
    """Assigning to a non-existent drone must return 404."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.post(
        "/api/master/drones/999999/payload",
        json={"payload_type_id": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_assign_payload_viewer_403(
    client: AsyncClient, viewer_user, drone_instance, make_token
):
    """VIEWER cannot assign a payload — requires FLIGHT_CONTROLLER."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        f"/api/master/drones/{drone_instance['id']}/payload",
        json={"payload_type_id": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_assign_payload_unauthenticated_401(
    client: AsyncClient, drone_instance
):
    """Unauthenticated request must return 401."""
    resp = await client.post(
        f"/api/master/drones/{drone_instance['id']}/payload",
        json={"payload_type_id": None},
    )
    assert resp.status_code == 401
