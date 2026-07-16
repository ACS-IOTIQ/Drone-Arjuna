"""
Drone Flight — Mission CRUD & Upload tests
==========================================
Tests cover three endpoint groups not addressed in
test_mission_payload_weight.py:

  1. GET /api/flight/missions  (list)
       - empty list → 200 []
       - missions appear after creation, ordered newest-first
       - waypoints embedded in each mission object
       - viewer can read (VIEWER+ required)
       - unauthenticated → 401

  2. DELETE /api/flight/missions/{id}
       - success → 204, mission gone afterwards
       - non-existent ID → 404
       - executing mission → 409
       - viewer → 403 (requires FLIGHT_CONTROLLER+)
       - unauthenticated → 401

  3. POST /api/flight/missions/{id}/upload  (additional cases)
       - drone assigned but not connected to MAVLink → 503
       - mission fails pre-upload validation (overweight payload) → 422
       - unauthenticated → 401
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.tests.helpers import auth_headers


# ── Shared waypoints ──────────────────────────────────────────────────────────

_HOME_WP = {
    "sequence":     1,
    "latitude":     12.9716,
    "longitude":    77.5946,
    "altitude_m":   0.0,
    "altitude_ref": "AGL",
    "action":       "none",
    "is_home":      True,
}
_TARGET_WP = {
    "sequence":     2,
    "latitude":     12.9800,
    "longitude":    77.6000,
    "altitude_m":   80.0,
    "altitude_ref": "AGL",
    "action":       "none",
}

_DT_BODY = {
    "name":                  "FM-Test-DroneType",
    "manufacturer":          "ACS Systems",
    "model":                 "FM-Alpha",
    "size_class":            "medium",
    "mission_type":          "ISR",
    "is_vtol":               True,
    "max_speed_ms":          30.0,
    "cruise_speed_ms":       20.0,
    "max_altitude_m":        500.0,
    "endurance_h":           4.0,
    "range_km":              100.0,
    "max_takeoff_weight_kg": 20.0,
    "max_payload_weight_kg": 5.0,
    "autopilot_type":        "ArduPilot",
}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def drone_type(client: AsyncClient, admin_user, make_token):
    """Creates a DroneType; deletes it on teardown."""
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.post("/api/master/drone-types", json=_DT_BODY, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/master/drone-types/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def drone_instance(client: AsyncClient, admin_user, drone_type, make_token):
    """Creates a DroneInstance linked to drone_type."""
    hdrs = auth_headers(admin_user, make_token)
    body = {
        "call_sign":      "FM-ALPHA-01",
        "serial_number":  "FM-SN-001",
        "drone_type_id":  drone_type["id"],
    }
    resp = await client.post("/api/master/drones", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    yield resp.json()


async def _make_mission(
    client: AsyncClient,
    hdrs: dict,
    *,
    name: str = "FM-Test-Mission",
    drone_instance_id: int | None = None,
    payload_weight_kg: float | None = None,
    waypoints: list | None = None,
) -> dict:
    """Helper: POST a mission and return its JSON body."""
    body: dict = {
        "name":         name,
        "mission_type": "ISR",
        "waypoints":    waypoints if waypoints is not None else [_HOME_WP, _TARGET_WP],
    }
    if drone_instance_id is not None:
        body["drone_instance_id"] = drone_instance_id
    if payload_weight_kg is not None:
        body["payload_weight_kg"] = payload_weight_kg
    resp = await client.post("/api/flight/missions", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ═══════════════════════════════════════════════════════════════════════
# 1. GET /api/flight/missions — list
# ═══════════════════════════════════════════════════════════════════════

async def test_list_missions_empty_200(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    When no missions exist the endpoint must return HTTP 200 with an
    empty list, not 404.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    resp = await client.get("/api/flight/missions", headers=hdrs)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_missions_returns_created_missions(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    Missions created via POST must appear in the GET list response.
    Each item must carry its id, name, mission_type, and a waypoints list.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    m1 = await _make_mission(client, hdrs, name="List-Mission-A")
    m2 = await _make_mission(client, hdrs, name="List-Mission-B")
    try:
        resp = await client.get("/api/flight/missions", headers=hdrs)
        assert resp.status_code == 200
        data = resp.json()
        ids = [m["id"] for m in data]
        assert m1["id"] in ids
        assert m2["id"] in ids
        # Each object must have embedded waypoints
        for item in data:
            assert "waypoints" in item
            assert isinstance(item["waypoints"], list)
    finally:
        await client.delete(f"/api/flight/missions/{m1['id']}", headers=hdrs)
        await client.delete(f"/api/flight/missions/{m2['id']}", headers=hdrs)


async def test_list_missions_ordered_newest_first(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    The list must be ordered newest-first (created_at DESC).
    The second mission created should appear before the first.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    m1 = await _make_mission(client, hdrs, name="Ordered-First")
    m2 = await _make_mission(client, hdrs, name="Ordered-Second")
    try:
        resp = await client.get("/api/flight/missions", headers=hdrs)
        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()]
        assert ids.index(m2["id"]) < ids.index(m1["id"])
    finally:
        await client.delete(f"/api/flight/missions/{m1['id']}", headers=hdrs)
        await client.delete(f"/api/flight/missions/{m2['id']}", headers=hdrs)


async def test_list_missions_viewer_can_read(
    client: AsyncClient, viewer_user, flight_controller_user, make_token
):
    """
    VIEWER role must be able to list missions (read-only access).
    """
    fc_hdrs  = auth_headers(flight_controller_user, make_token)
    vw_hdrs  = auth_headers(viewer_user, make_token)
    m = await _make_mission(client, fc_hdrs, name="Viewer-List-Test")
    try:
        resp = await client.get("/api/flight/missions", headers=vw_hdrs)
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()]
        assert m["id"] in ids
    finally:
        await client.delete(f"/api/flight/missions/{m['id']}", headers=fc_hdrs)


async def test_list_missions_unauthenticated_401(client: AsyncClient):
    """No Bearer token on the list endpoint must return 401."""
    resp = await client.get("/api/flight/missions")
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════
# 2. DELETE /api/flight/missions/{id}
# ═══════════════════════════════════════════════════════════════════════

async def test_create_mission_rejects_waypoint_leg_touching_restricted_zone(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    Waypoints can both be outside a restricted zone while the straight mission
    leg between them clips it. Mission creation must reject that route.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    waypoints = [
        {
            "sequence": 1,
            "latitude": 28.5562,
            "longitude": 76.9600,
            "altitude_m": 0.0,
            "altitude_ref": "AGL",
            "action": "none",
            "is_home": True,
        },
        {
            "sequence": 2,
            "latitude": 28.5562,
            "longitude": 77.2400,
            "altitude_m": 80.0,
            "altitude_ref": "AGL",
            "action": "none",
        },
    ]

    resp = await client.post(
        "/api/flight/missions",
        json={
            "name": "Restricted-Zone-Touch-Test",
            "mission_type": "ISR",
            "waypoints": waypoints,
        },
        headers=hdrs,
    )

    assert resp.status_code == 422
    errors = resp.json()["detail"]["errors"]
    assert any("Mission leg" in error for error in errors)
    assert any("Delhi IGI Airport" in error for error in errors)
    assert any("touches or crosses" in error for error in errors)


async def test_delete_mission_204(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    DELETE on an existing mission must return 204 and the mission must
    no longer be accessible via GET.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    m = await _make_mission(client, hdrs, name="Delete-Me-Mission")

    delete_resp = await client.delete(f"/api/flight/missions/{m['id']}", headers=hdrs)
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/api/flight/missions/{m['id']}", headers=hdrs)
    assert get_resp.status_code == 404


async def test_delete_mission_not_found_404(
    client: AsyncClient, flight_controller_user, make_token
):
    """Deleting a non-existent mission ID must return 404."""
    hdrs = auth_headers(flight_controller_user, make_token)
    resp = await client.delete("/api/flight/missions/999999", headers=hdrs)
    assert resp.status_code == 404


async def test_delete_executing_mission_409(
    client: AsyncClient, admin_user, flight_controller_user, make_token
):
    """
    A mission whose status has been set to 'executing' must NOT be
    deletable — the endpoint must return 409.
    The status patch requires MISSION_COMMANDER; admin fulfils that role.
    """
    fc_hdrs    = auth_headers(flight_controller_user, make_token)
    admin_hdrs = auth_headers(admin_user, make_token)

    m = await _make_mission(client, fc_hdrs, name="Executing-Mission")

    # Promote to executing status via admin
    patch = await client.patch(
        f"/api/flight/missions/{m['id']}/status",
        json={"status": "executing"},
        headers=admin_hdrs,
    )
    assert patch.status_code == 200

    # Attempt to delete the executing mission
    delete_resp = await client.delete(
        f"/api/flight/missions/{m['id']}", headers=fc_hdrs
    )
    assert delete_resp.status_code == 409

    # Restore to approved so teardown delete succeeds
    await client.patch(
        f"/api/flight/missions/{m['id']}/status",
        json={"status": "approved"},
        headers=admin_hdrs,
    )
    await client.delete(f"/api/flight/missions/{m['id']}", headers=fc_hdrs)


async def test_delete_mission_viewer_403(
    client: AsyncClient, viewer_user, flight_controller_user, make_token
):
    """VIEWER must receive 403 when trying to delete a mission."""
    fc_hdrs = auth_headers(flight_controller_user, make_token)
    vw_hdrs = auth_headers(viewer_user, make_token)

    m = await _make_mission(client, fc_hdrs, name="Viewer-Delete-Blocked")
    try:
        resp = await client.delete(f"/api/flight/missions/{m['id']}", headers=vw_hdrs)
        assert resp.status_code == 403
    finally:
        await client.delete(f"/api/flight/missions/{m['id']}", headers=fc_hdrs)


async def test_delete_mission_unauthenticated_401(
    client: AsyncClient, flight_controller_user, make_token
):
    """No Bearer token on DELETE must return 401."""
    hdrs = auth_headers(flight_controller_user, make_token)
    m = await _make_mission(client, hdrs, name="Unauth-Delete-Mission")
    try:
        resp = await client.delete(f"/api/flight/missions/{m['id']}")
        assert resp.status_code == 401
    finally:
        await client.delete(f"/api/flight/missions/{m['id']}", headers=hdrs)


# ═══════════════════════════════════════════════════════════════════════
# 3. POST /api/flight/missions/{id}/upload — additional cases
# ═══════════════════════════════════════════════════════════════════════

async def test_upload_drone_not_connected_503(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """
    When a drone IS assigned to the mission but is not connected to
    MAVLink (no SITL in the test environment), the upload endpoint must
    return HTTP 503.

    The upload_to_drone flow checks validation first; to reach the MAVLink
    connection check the mission must pass all validation rules, which it
    does here (valid waypoints, payload within limits, altitude within
    ceiling).
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    m = await _make_mission(
        client, hdrs,
        name="Upload-503-Mission",
        drone_instance_id=drone_instance["id"],
        payload_weight_kg=2.0,      # well within 5 kg limit
    )
    try:
        resp = await client.post(
            f"/api/flight/missions/{m['id']}/upload", headers=hdrs
        )
        assert resp.status_code == 503
        assert "not connected" in resp.json()["detail"].lower()
    finally:
        await client.delete(f"/api/flight/missions/{m['id']}", headers=hdrs)


async def test_upload_invalid_mission_422(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """
    Pre-upload validation runs before the MAVLink connection check.
    A mission with payload exceeding the drone's max_payload_weight_kg
    (5 kg limit) must return 422 with a validation error body — it never
    reaches the MAVLink layer.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    m = await _make_mission(
        client, hdrs,
        name="Upload-422-Mission",
        drone_instance_id=drone_instance["id"],
        payload_weight_kg=20.0,     # far exceeds 5 kg limit → validation fails
    )
    try:
        resp = await client.post(
            f"/api/flight/missions/{m['id']}/upload", headers=hdrs
        )
        assert resp.status_code == 422
        body = resp.json()
        assert "detail" in body
        # Errors list must mention payload
        detail = body["detail"]
        errors = detail.get("errors", []) if isinstance(detail, dict) else []
        assert any("payload" in e.lower() for e in errors)
    finally:
        await client.delete(f"/api/flight/missions/{m['id']}", headers=hdrs)


async def test_upload_mission_unauthenticated_401(
    client: AsyncClient, flight_controller_user, make_token
):
    """No Bearer token on the upload endpoint must return 401."""
    hdrs = auth_headers(flight_controller_user, make_token)
    m = await _make_mission(client, hdrs, name="Upload-Unauth-Mission")
    try:
        resp = await client.post(f"/api/flight/missions/{m['id']}/upload")
        assert resp.status_code == 401
    finally:
        await client.delete(f"/api/flight/missions/{m['id']}", headers=hdrs)


# ══════════════════════════════════════════════════════════════════════
# GET /api/flight/missions/{id}
# ══════════════════════════════════════════════════════════════════════

async def test_get_mission_by_id_200(
    client: AsyncClient, flight_controller_user, make_token
):
    """GET by ID returns mission with waypoints list."""
    hdrs = auth_headers(flight_controller_user, make_token)
    m = await _make_mission(client, hdrs, name="GetById-Mission")
    try:
        resp = await client.get(
            f"/api/flight/missions/{m['id']}",
            headers=hdrs,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"]   == m["id"]
        assert data["name"] == "GetById-Mission"
        assert "waypoints"  in data
        assert isinstance(data["waypoints"], list)
    finally:
        await client.delete(f"/api/flight/missions/{m['id']}", headers=hdrs)


async def test_get_mission_by_id_not_found_404(
    client: AsyncClient, viewer_user, make_token
):
    """GET on a non-existent mission ID must return 404."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/flight/missions/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_get_mission_by_id_unauthenticated_401(client: AsyncClient):
    """GET without a token must return 401."""
    resp = await client.get("/api/flight/missions/1")
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# POST /api/flight/missions/{id}/validate
# ══════════════════════════════════════════════════════════════════════

async def test_validate_mission_200(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    Valid mission → 200 with {valid, errors, warnings} shape.
    No drone assigned so the validator skips drone-type checks
    and returns valid=True with an empty errors list.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    m = await _make_mission(client, hdrs, name="Validate-OK-Mission")
    try:
        resp = await client.post(
            f"/api/flight/missions/{m['id']}/validate",
            headers=hdrs,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "valid"    in body
        assert "errors"   in body
        assert "warnings" in body
        assert isinstance(body["errors"],   list)
        assert isinstance(body["warnings"], list)
    finally:
        await client.delete(f"/api/flight/missions/{m['id']}", headers=hdrs)


async def test_validate_mission_not_found_404(
    client: AsyncClient, flight_controller_user, make_token
):
    """Non-existent mission ID → 404."""
    hdrs = auth_headers(flight_controller_user, make_token)
    resp = await client.post(
        "/api/flight/missions/999999/validate",
        headers=hdrs,
    )
    assert resp.status_code == 404


async def test_validate_mission_viewer_403(
    client: AsyncClient, viewer_user, make_token
):
    """VIEWER role cannot validate (requires FLIGHT_CONTROLLER+) → 403."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.post(
        "/api/flight/missions/1/validate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_validate_mission_unauthenticated_401(client: AsyncClient):
    """No token → 401."""
    resp = await client.post("/api/flight/missions/1/validate")
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════
# PATCH /api/flight/missions/{mid} — update mission
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_update_mission_geofence_200(
    client: AsyncClient, flight_controller_user, make_token
):
    """Update a planning-status mission's geofence and verify it persists."""
    hdrs = auth_headers(flight_controller_user, make_token)
    m = await _make_mission(client, hdrs)
    try:
        geofence = {
            "type": "Polygon",
            "coordinates": [[[77.5, 12.9], [77.6, 12.9], [77.6, 13.0], [77.5, 13.0], [77.5, 12.9]]],
        }
        resp = await client.patch(
            f"/api/flight/missions/{m['id']}",
            json={"geofence": geofence},
            headers=hdrs,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["geofence"] == geofence
    finally:
        await client.delete(f"/api/flight/missions/{m['id']}", headers=hdrs)


@pytest.mark.asyncio
async def test_update_mission_name_and_waypoints_200(
    client: AsyncClient, flight_controller_user, make_token
):
    """Update mission name and replace waypoints."""
    hdrs = auth_headers(flight_controller_user, make_token)
    m = await _make_mission(client, hdrs)
    try:
        new_wp = {
            "sequence": 1, "latitude": 12.95, "longitude": 77.55,
            "altitude_m": 100.0, "action": "none", "is_home": True,
        }
        resp = await client.patch(
            f"/api/flight/missions/{m['id']}",
            json={"name": "Updated Mission Name", "waypoints": [new_wp]},
            headers=hdrs,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Updated Mission Name"
        assert len(body["waypoints"]) == 1
        assert body["waypoints"][0]["latitude"] == 12.95
    finally:
        await client.delete(f"/api/flight/missions/{m['id']}", headers=hdrs)


@pytest.mark.asyncio
async def test_update_mission_non_planning_status_409(
    client: AsyncClient, flight_controller_user, mission_commander_user, make_token
):
    """Cannot edit a mission that is not in 'planning' status → 409."""
    fc_hdrs = auth_headers(flight_controller_user, make_token)
    mc_hdrs = auth_headers(mission_commander_user, make_token)
    m = await _make_mission(client, fc_hdrs)
    try:
        # Approve the mission
        approve = await client.patch(
            f"/api/flight/missions/{m['id']}/status",
            json={"status": "approved"},
            headers=mc_hdrs,
        )
        assert approve.status_code == 200

        resp = await client.patch(
            f"/api/flight/missions/{m['id']}",
            json={"name": "Should Fail"},
            headers=fc_hdrs,
        )
        assert resp.status_code == 409
    finally:
        # Reset to planning so delete works
        await client.patch(
            f"/api/flight/missions/{m['id']}/status",
            json={"status": "planning"},
            headers=mc_hdrs,
        )
        await client.delete(f"/api/flight/missions/{m['id']}", headers=fc_hdrs)


@pytest.mark.asyncio
async def test_update_mission_not_found_404(
    client: AsyncClient, flight_controller_user, make_token
):
    """Non-existent mission → 404."""
    hdrs = auth_headers(flight_controller_user, make_token)
    resp = await client.patch(
        "/api/flight/missions/999999",
        json={"name": "Ghost"},
        headers=hdrs,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_mission_viewer_403(
    client: AsyncClient, viewer_user, make_token
):
    """VIEWER cannot update mission → 403."""
    hdrs = {"Authorization": f"Bearer {make_token(viewer_user.id, viewer_user.role)}"}
    resp = await client.patch("/api/flight/missions/1", json={"name": "X"}, headers=hdrs)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_mission_unauthenticated_401(client: AsyncClient):
    """No token → 401."""
    resp = await client.patch("/api/flight/missions/1", json={"name": "X"})
    assert resp.status_code == 401
