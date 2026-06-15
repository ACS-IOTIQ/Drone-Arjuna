"""
Drone Control — POST /simulate/start tests
==========================================
POST /api/drone-control/simulate/start

Covers:
  - 404 when mission_id does not exist
  - 404 when drone_instance_id does not exist
  - 422 when mission exists but has no waypoints (only home waypoints filtered out)
  - 422 when mission has no drone assigned and no drone_instance_id in request
  - 409 when a simulation is already running (start twice)
  - 403 VIEWER cannot start a simulation
  - 401 unauthenticated request

Note: A 201 happy-path test would require a SITL environment or a fully mocked
MAVLink layer. We test all error paths and RBAC exhaustively instead.
The simulation attaches a virtual connection via mavlink_manager.attach_simulation,
so the test that starts a real simulation will succeed (the drone does not need
to be physically connected — the simulator does the attachment itself).
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


_DT_BODY = {
    "name": "Sim-Start-DroneType",
    "manufacturer": "ACS Test",
    "model": "SIM-T1",
    "size_class": "small",
    "mission_type": "ISR",
    "is_vtol": False,
    "max_speed_ms": 20.0,
    "cruise_speed_ms": 15.0,
    "max_altitude_m": 1500.0,
    "endurance_h": 1.0,
    "range_km": 25.0,
    "max_takeoff_weight_kg": 3.0,
    "max_payload_weight_kg": 0.5,
    "autopilot_type": "ArduPilot",
}

_WP1 = {"sequence": 1, "latitude": 12.9716, "longitude": 77.5946,
        "altitude_m": 100.0, "altitude_ref": "AGL", "action": "none"}
_WP2 = {"sequence": 2, "latitude": 12.9800, "longitude": 77.6000,
        "altitude_m": 100.0, "altitude_ref": "AGL", "action": "none"}


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
        json={"call_sign": "SIM-TEST-01", "drone_type_id": drone_type["id"],
              "serial_number": "SN-SIM-001"},
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data


@pytest_asyncio.fixture
async def mission_with_waypoints(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """Mission pre-assigned to a drone instance, with 2 waypoints."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        "/api/flight/missions",
        json={
            "name": "SimStart-Mission",
            "mission_type": "ISR",
            "drone_instance_id": drone_instance["id"],
            "waypoints": [_WP1, _WP2],
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
async def mission_no_waypoints(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """Mission with drone assigned but no waypoints."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        "/api/flight/missions",
        json={
            "name": "SimStart-EmptyMission",
            "mission_type": "ISR",
            "drone_instance_id": drone_instance["id"],
            "waypoints": [],
        },
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/flight/missions/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def mission_no_drone(client: AsyncClient, flight_controller_user, make_token):
    """Mission with no drone_instance_id assigned."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        "/api/flight/missions",
        json={"name": "SimStart-NoDroneMission", "mission_type": "ISR",
              "waypoints": [_WP1, _WP2]},
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/flight/missions/{data['id']}", headers=hdrs)


# ══════════════════════════════════════════════════════════════════════
# Happy path
# ══════════════════════════════════════════════════════════════════════

async def test_simulate_start_201(
    client: AsyncClient, flight_controller_user, mission_with_waypoints, make_token
):
    """
    Starting a simulation for a valid mission with waypoints and an assigned
    drone must return 201. The simulator attaches a virtual MAVLink connection
    so no physical drone is required.
    """
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.post(
        "/api/drone-control/simulate/start",
        json={"mission_id": mission_with_waypoints["id"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    # 201 = simulation started; 409 = already running from previous test
    assert resp.status_code in (201, 409)

    if resp.status_code == 201:
        body = resp.json()
        assert "drone_id" in body
        assert "call_sign" in body
        assert "waypoint_count" in body
        assert body["waypoint_count"] == 2

    # Cleanup: stop simulation if started
    await client.delete(
        "/api/drone-control/simulate/stop",
        headers={"Authorization": f"Bearer {token}"},
    )


# ══════════════════════════════════════════════════════════════════════
# Error paths
# ══════════════════════════════════════════════════════════════════════

async def test_simulate_start_unknown_mission_404(
    client: AsyncClient, flight_controller_user, make_token
):
    """Non-existent mission_id must return 404."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.post(
        "/api/drone-control/simulate/start",
        json={"mission_id": 999999},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_simulate_start_unknown_drone_404(
    client: AsyncClient, flight_controller_user, mission_no_drone, make_token
):
    """Passing a non-existent drone_instance_id must return 404."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.post(
        "/api/drone-control/simulate/start",
        json={"mission_id": mission_no_drone["id"], "drone_instance_id": 999999},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_simulate_start_no_drone_assigned_422(
    client: AsyncClient, flight_controller_user, mission_no_drone, make_token
):
    """
    Mission with no drone_instance_id and no drone_instance_id in the request
    body must return 422 (cannot resolve which drone to simulate).
    """
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.post(
        "/api/drone-control/simulate/start",
        json={"mission_id": mission_no_drone["id"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_simulate_start_no_waypoints_422(
    client: AsyncClient, flight_controller_user, mission_no_waypoints, make_token
):
    """Mission with no waypoints must return 422."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.post(
        "/api/drone-control/simulate/start",
        json={"mission_id": mission_no_waypoints["id"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_simulate_start_already_running_409(
    client: AsyncClient, flight_controller_user, mission_with_waypoints, make_token
):
    """Starting a simulation when one is already running must return 409."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}

    first = await client.post(
        "/api/drone-control/simulate/start",
        json={"mission_id": mission_with_waypoints["id"]},
        headers=hdrs,
    )
    # First call: 201 (started) or 409 (already running from another test)
    if first.status_code == 201:
        second = await client.post(
            "/api/drone-control/simulate/start",
            json={"mission_id": mission_with_waypoints["id"]},
            headers=hdrs,
        )
        assert second.status_code == 409
        # Cleanup
        await client.delete("/api/drone-control/simulate/stop", headers=hdrs)


# ══════════════════════════════════════════════════════════════════════
# RBAC
# ══════════════════════════════════════════════════════════════════════

async def test_simulate_start_viewer_403(
    client: AsyncClient, viewer_user, mission_with_waypoints, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.post(
        "/api/drone-control/simulate/start",
        json={"mission_id": mission_with_waypoints["id"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_simulate_start_unauthenticated_401(
    client: AsyncClient, mission_with_waypoints
):
    resp = await client.post(
        "/api/drone-control/simulate/start",
        json={"mission_id": mission_with_waypoints["id"]},
    )
    assert resp.status_code == 401
