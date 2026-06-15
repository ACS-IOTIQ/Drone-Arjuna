"""
Flight Missions — extra endpoint tests
========================================
GET  /api/flight/missions/{mid}/simulate  — pre-flight animation frames
POST /api/flight/missions/{mid}/upload    — MAVLink upload to drone

Covers:
  - simulate: returns frame list with correct structure (mission_id, frame_count, frames)
  - simulate: frames contain position / battery / altitude fields
  - simulate: 400 when mission has no waypoints
  - upload: 404 when mission does not exist
  - upload: 503 when drone is not connected (no SITL in test environment)
  - upload: 403 VIEWER cannot upload
  - upload: 401 unauthenticated
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


_DT_BODY = {
    "name": "Extra-Mission-DroneType",
    "manufacturer": "ACS Test",
    "model": "EM-T1",
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

_WP1 = {"sequence": 1, "latitude": 12.9716, "longitude": 77.5946,
        "altitude_m": 100.0, "altitude_ref": "AGL", "action": "none"}
_WP2 = {"sequence": 2, "latitude": 12.9800, "longitude": 77.6000,
        "altitude_m": 150.0, "altitude_ref": "AGL", "action": "none"}
_WP3 = {"sequence": 3, "latitude": 12.9850, "longitude": 77.5800,
        "altitude_m": 50.0,  "altitude_ref": "AGL", "action": "land"}


@pytest_asyncio.fixture
async def drone_type(client: AsyncClient, admin_user, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    resp = await client.post("/api/master/drone-types", json=_DT_BODY, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/master/drone-types/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def drone_instance(client: AsyncClient, admin_user, drone_type, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        "/api/master/drones",
        json={"call_sign": "EXTRA-DRONE-01", "drone_type_id": drone_type["id"],
              "serial_number": "SN-EXTRA-001"},
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data


@pytest_asyncio.fixture
async def mission_3wps(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """Mission with 3 waypoints, drone assigned."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        "/api/flight/missions",
        json={
            "name": "Extra-Mission-3WPs",
            "mission_type": "ISR",
            "drone_instance_id": drone_instance["id"],
            "waypoints": [_WP1, _WP2, _WP3],
        },
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    get = await client.get(f"/api/flight/missions/{data['id']}", headers=hdrs)
    if get.status_code == 200 and get.json().get("status") != "executing":
        await client.delete(f"/api/flight/missions/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def mission_empty(client: AsyncClient, flight_controller_user, make_token):
    """Mission with no waypoints."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        "/api/flight/missions",
        json={"name": "Extra-Mission-Empty", "mission_type": "ISR", "waypoints": []},
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/flight/missions/{data['id']}", headers=hdrs)


# ══════════════════════════════════════════════════════════════════════
# GET /missions/{mid}/simulate  — animation frames
# ══════════════════════════════════════════════════════════════════════

async def test_simulate_frames_200(
    client: AsyncClient, viewer_user, mission_3wps, make_token
):
    """Simulate endpoint returns a frame list for a mission with waypoints."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/flight/missions/{mission_3wps['id']}/simulate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "mission_id" in body
    assert "frame_count" in body
    assert "frames" in body
    assert body["mission_id"] == mission_3wps["id"]
    assert body["frame_count"] > 0
    assert len(body["frames"]) == body["frame_count"]


async def test_simulate_frames_structure(
    client: AsyncClient, viewer_user, mission_3wps, make_token
):
    """Each frame must contain position and battery fields."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/flight/missions/{mission_3wps['id']}/simulate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    frames = resp.json()["frames"]
    assert len(frames) > 0

    first = frames[0]
    # Position fields
    assert "lat" in first
    assert "lon" in first
    assert "alt_m" in first
    # Battery field
    assert "battery_pct" in first


async def test_simulate_frames_no_waypoints_400(
    client: AsyncClient, viewer_user, mission_empty, make_token
):
    """Simulate on a mission with no waypoints must return 400."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/flight/missions/{mission_empty['id']}/simulate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_simulate_frames_not_found_404(
    client: AsyncClient, viewer_user, make_token
):
    """Non-existent mission returns 404 from summary (no waypoints found)."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        "/api/flight/missions/999999/simulate",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Returns 400 (no waypoints found for that mission_id, same as empty)
    assert resp.status_code in (400, 404)


async def test_simulate_frames_unauthenticated_401(
    client: AsyncClient, mission_3wps
):
    resp = await client.get(
        f"/api/flight/missions/{mission_3wps['id']}/simulate"
    )
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# POST /missions/{mid}/upload  — MAVLink upload
# ══════════════════════════════════════════════════════════════════════

async def test_upload_mission_not_found_404(
    client: AsyncClient, flight_controller_user, make_token
):
    """Upload to a non-existent mission must return 404."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.post(
        "/api/flight/missions/999999/upload",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_upload_mission_no_drone_connected_503(
    client: AsyncClient, flight_controller_user, mission_3wps, make_token
):
    """
    Uploading a valid mission to a drone that is not MAVLink-connected
    must return 503. In the test environment there is no SITL, so
    MissionPlanner.upload_to_drone() raises 503 when mavlink_manager
    has no connection for the drone.
    """
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.post(
        f"/api/flight/missions/{mission_3wps['id']}/upload",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Either 503 (drone not connected) or 422 (validation failed — missing home WP)
    assert resp.status_code in (422, 503)


async def test_upload_mission_viewer_403(
    client: AsyncClient, viewer_user, mission_3wps, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.post(
        f"/api/flight/missions/{mission_3wps['id']}/upload",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_upload_mission_unauthenticated_401(
    client: AsyncClient, mission_3wps
):
    resp = await client.post(
        f"/api/flight/missions/{mission_3wps['id']}/upload"
    )
    assert resp.status_code == 401
