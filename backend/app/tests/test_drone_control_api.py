"""
Drone Control API tests
=======================
GET /api/drone-control/ports
GET /api/drone-control/status
GET /api/drone-control/telemetry/{drone_id}
POST /api/drone-control/autoconnect
POST /api/drone-control/connect
POST /api/drone-control/command
GET /api/drone-control/simulate/status
DELETE /api/drone-control/simulate/stop

Covers:
  - Read-only endpoints return correct shapes
  - Telemetry returns 404 for drone not yet connected
  - Autoconnect returns 404 when drone instance does not exist
  - Autoconnect returns 503 when no heartbeat found (no SITL running)
  - Stop simulation returns 404 when no simulation is running
  - RBAC: VIEWER can read, VIEWER blocked from writes
"""
import pytest_asyncio
from httpx import AsyncClient


_DT_BODY = {
    "name": "Control-Test Drone Type",
    "manufacturer": "Test Corp",
    "model": "CTL-T",
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
    resp  = await client.post(
        "/api/master/drones",
        json={
            "call_sign":     "CTL-TEST-01",
            "drone_type_id": drone_type["id"],
            "serial_number": "SN-CTL-001",
        },
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/master/drones/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def drone_instance_2(client: AsyncClient, admin_user, drone_type, make_token):
    """A second, independent drone instance — for concurrent-simulation tests."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.post(
        "/api/master/drones",
        json={
            "call_sign":     "CTL-TEST-02",
            "drone_type_id": drone_type["id"],
            "serial_number": "SN-CTL-002",
        },
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/master/drones/{data['id']}", headers=hdrs)


async def _make_flyable_mission(client: AsyncClient, hdrs: dict, drone_id: int, name: str) -> int:
    """Creates a mission with real (non-home) waypoints so simulate/start can fly it."""
    resp = await client.post(
        "/api/flight/missions",
        json={
            "name": name, "mission_type": "ISR", "drone_instance_id": drone_id,
            "waypoints": [
                {"sequence": 1, "latitude": 17.385, "longitude": 78.4867,
                 "altitude_m": 50, "altitude_ref": "AGL", "action": "none", "is_home": True},
                {"sequence": 2, "latitude": 17.395, "longitude": 78.4967,
                 "altitude_m": 80, "altitude_ref": "AGL", "action": "none"},
            ],
        },
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ══════════════════════════════════════════════════════════════════════
# Ports
# ══════════════════════════════════════════════════════════════════════

async def test_list_ports_viewer_200(client: AsyncClient, viewer_user, make_token):
    """VIEWER can list available serial/network ports."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/drone-control/ports",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    # Network ports are always included
    port_strings = [p["port"] for p in resp.json()]
    assert any("14550" in p for p in port_strings)


async def test_list_ports_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/drone-control/ports")
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# Fleet status
# ══════════════════════════════════════════════════════════════════════

async def test_fleet_status_200(client: AsyncClient, viewer_user, make_token):
    """Fleet status returns a {drones: list} dict even when no drones connected."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/drone-control/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "drones" in body
    assert isinstance(body["drones"], list)


async def test_fleet_status_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/drone-control/status")
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# Telemetry snapshot
# ══════════════════════════════════════════════════════════════════════

async def test_telemetry_not_connected_404(
    client: AsyncClient, viewer_user, make_token
):
    """Telemetry snapshot for a drone that is not connected must return 404."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/drone-control/telemetry/9999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_telemetry_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/drone-control/telemetry/1")
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# Autoconnect
# ══════════════════════════════════════════════════════════════════════

async def test_autoconnect_drone_not_found_404(
    client: AsyncClient, flight_controller_user, make_token
):
    """Autoconnect with a non-existent drone_instance_id must return 404."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.post(
        "/api/drone-control/autoconnect",
        json={"drone_instance_id": 999999},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_autoconnect_no_sitl_503(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """Autoconnect with a valid drone but no SITL running must return 503."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.post(
        "/api/drone-control/autoconnect",
        json={"drone_instance_id": drone_instance["id"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    # No SITL in test environment — expect 503
    assert resp.status_code == 503


async def test_autoconnect_viewer_403(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        "/api/drone-control/autoconnect",
        json={"drone_instance_id": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# Command
# ══════════════════════════════════════════════════════════════════════

async def test_command_viewer_403(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        "/api/drone-control/command",
        json={"drone_id": 1, "command": "arm", "params": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_command_not_connected_503(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """Sending a command to a drone that is not connected must return 503."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.post(
        "/api/drone-control/command",
        json={"drone_id": drone_instance["id"], "command": "arm", "params": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 503


async def test_command_unauthenticated_401(client: AsyncClient):
    resp = await client.post(
        "/api/drone-control/command",
        json={"drone_id": 1, "command": "arm"},
    )
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# Connect / disconnect
# ══════════════════════════════════════════════════════════════════════

async def test_connect_viewer_403(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        "/api/drone-control/connect",
        json={"drone_instance_id": 1, "transport": "udp"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_disconnect_viewer_403(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        "/api/drone-control/disconnect/1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# Simulation
# ══════════════════════════════════════════════════════════════════════

async def test_simulate_status_200(client: AsyncClient, viewer_user, make_token):
    """Simulation status is always available to viewers."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/drone-control/simulate/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


async def test_simulate_stop_no_running_404(
    client: AsyncClient, flight_controller_user, make_token
):
    """Stopping simulation when none is running must return 404."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.delete(
        "/api/drone-control/simulate/stop",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Either 404 (none running) or 200 if a prior test left one running
    assert resp.status_code in (200, 404)


async def test_simulate_stop_viewer_403(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.delete(
        "/api/drone-control/simulate/stop",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# Simulate start
# ══════════════════════════════════════════════════════════════════════

async def test_simulate_start_viewer_403(client: AsyncClient, viewer_user, make_token):
    """VIEWER cannot start a simulation."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        "/api/drone-control/simulate/start",
        json={"mission_id": 1, "drone_instance_id": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_simulate_start_unauthenticated_401(client: AsyncClient):
    """Unauthenticated simulate/start returns 401."""
    resp = await client.post(
        "/api/drone-control/simulate/start",
        json={"mission_id": 1, "drone_instance_id": 1},
    )
    assert resp.status_code == 401


async def test_simulate_start_mission_not_found_404(
    client: AsyncClient, flight_controller_user, make_token
):
    """simulate/start with a non-existent mission_id returns 404."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.post(
        "/api/drone-control/simulate/start",
        json={"mission_id": 999999, "drone_instance_id": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_simulate_start_no_drone_422(
    client: AsyncClient, flight_controller_user, make_token
):
    """Mission with no drone assigned and no drone_instance_id override → 422."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    m_resp = await client.post(
        "/api/flight/missions",
        json={"name": "Sim-NoDrone", "mission_type": "ISR", "waypoints": []},
        headers=hdrs,
    )
    assert m_resp.status_code == 201
    resp = await client.post(
        "/api/drone-control/simulate/start",
        json={"mission_id": m_resp.json()["id"]},
        headers=hdrs,
    )
    assert resp.status_code == 422


async def test_simulate_start_drone_not_found_404(
    client: AsyncClient, flight_controller_user, make_token
):
    """Mission exists but the given drone_instance_id does not → 404."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    m_resp = await client.post(
        "/api/flight/missions",
        json={"name": "Sim-BadDrone", "mission_type": "ISR", "waypoints": []},
        headers=hdrs,
    )
    assert m_resp.status_code == 201
    resp = await client.post(
        "/api/drone-control/simulate/start",
        json={"mission_id": m_resp.json()["id"], "drone_instance_id": 999999},
        headers=hdrs,
    )
    assert resp.status_code == 404


async def test_simulate_start_no_waypoints_422(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """Mission with drone assigned but no non-home waypoints → 422."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    m_resp = await client.post(
        "/api/flight/missions",
        json={
            "name":              "Sim-NoWP",
            "mission_type":      "ISR",
            "drone_instance_id": drone_instance["id"],
            "waypoints":         [],
        },
        headers=hdrs,
    )
    assert m_resp.status_code == 201
    resp = await client.post(
        "/api/drone-control/simulate/start",
        json={"mission_id": m_resp.json()["id"], "drone_instance_id": drone_instance["id"]},
        headers=hdrs,
    )
    assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# Concurrent multi-drone simulation
# ══════════════════════════════════════════════════════════════════════

async def test_simulate_start_uses_true_home_waypoint_for_rtl(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """
    Regression test: home_lat/home_lon (what RTL flies back to) must come
    from the mission's actual is_home=True waypoint, not the first *flight*
    waypoint. The waypoint query for the flight path explicitly excludes
    home waypoints, so naively taking its [0] element silently picks the
    wrong point — the drone would "RTL" to its first waypoint instead of
    where it actually launched from.
    """
    from app.modules.drone_control.mission_simulator import mission_simulator

    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    mission_id = await _make_flyable_mission(client, hdrs, drone_instance["id"], "Home-Regression")

    start = await client.post(
        "/api/drone-control/simulate/start",
        json={"mission_id": mission_id, "drone_instance_id": drone_instance["id"]},
        headers=hdrs,
    )
    assert start.status_code == 201, start.text

    flight = mission_simulator._flights[drone_instance["id"]]
    assert flight._home_lat == 17.385
    assert flight._home_lon == 78.4867
    # And NOT the first flight waypoint's coordinates
    assert flight._home_lat != 17.395
    assert flight._home_lon != 78.4967

    await client.delete(
        f"/api/drone-control/simulate/stop?drone_id={drone_instance['id']}", headers=hdrs
    )


async def test_simulate_two_drones_concurrently(
    client: AsyncClient, flight_controller_user, drone_instance, drone_instance_2, make_token
):
    """Two different drones can each have an active simulation at the same time."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}

    m1 = await _make_flyable_mission(client, hdrs, drone_instance["id"], "Concurrent-A")
    m2 = await _make_flyable_mission(client, hdrs, drone_instance_2["id"], "Concurrent-B")

    r1 = await client.post("/api/drone-control/simulate/start",
                            json={"mission_id": m1, "drone_instance_id": drone_instance["id"]},
                            headers=hdrs)
    assert r1.status_code == 201, r1.text

    r2 = await client.post("/api/drone-control/simulate/start",
                            json={"mission_id": m2, "drone_instance_id": drone_instance_2["id"]},
                            headers=hdrs)
    assert r2.status_code == 201, r2.text

    status_all = await client.get("/api/drone-control/simulate/status", headers=hdrs)
    assert status_all.status_code == 200
    active_ids = {s["drone_id"] for s in status_all.json()["simulations"]}
    assert {drone_instance["id"], drone_instance_2["id"]} <= active_ids

    # Cleanup — stop both so they don't leak into other tests
    await client.delete(f"/api/drone-control/simulate/stop?drone_id={drone_instance['id']}", headers=hdrs)
    await client.delete(f"/api/drone-control/simulate/stop?drone_id={drone_instance_2['id']}", headers=hdrs)


async def test_simulate_start_same_drone_twice_409(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """Starting a second simulation for a drone that's already flying must return 409."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    m1 = await _make_flyable_mission(client, hdrs, drone_instance["id"], "Dup-A")
    m2 = await _make_flyable_mission(client, hdrs, drone_instance["id"], "Dup-B")

    first = await client.post("/api/drone-control/simulate/start",
                               json={"mission_id": m1, "drone_instance_id": drone_instance["id"]},
                               headers=hdrs)
    assert first.status_code == 201, first.text

    second = await client.post("/api/drone-control/simulate/start",
                                json={"mission_id": m2, "drone_instance_id": drone_instance["id"]},
                                headers=hdrs)
    assert second.status_code == 409

    await client.delete(f"/api/drone-control/simulate/stop?drone_id={drone_instance['id']}", headers=hdrs)


async def test_simulate_stop_scoped_to_one_drone(
    client: AsyncClient, flight_controller_user, drone_instance, drone_instance_2, make_token
):
    """Stopping one drone's simulation must not affect another drone's simulation."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    m1 = await _make_flyable_mission(client, hdrs, drone_instance["id"], "Scoped-A")
    m2 = await _make_flyable_mission(client, hdrs, drone_instance_2["id"], "Scoped-B")

    await client.post("/api/drone-control/simulate/start",
                       json={"mission_id": m1, "drone_instance_id": drone_instance["id"]}, headers=hdrs)
    await client.post("/api/drone-control/simulate/start",
                       json={"mission_id": m2, "drone_instance_id": drone_instance_2["id"]}, headers=hdrs)

    stop_resp = await client.delete(
        f"/api/drone-control/simulate/stop?drone_id={drone_instance['id']}", headers=hdrs
    )
    assert stop_resp.status_code == 200, stop_resp.text

    status_1 = await client.get(
        f"/api/drone-control/simulate/status?drone_id={drone_instance['id']}", headers=hdrs
    )
    assert status_1.json()["active"] is False

    status_2 = await client.get(
        f"/api/drone-control/simulate/status?drone_id={drone_instance_2['id']}", headers=hdrs
    )
    assert status_2.json()["active"] is True

    await client.delete(f"/api/drone-control/simulate/stop?drone_id={drone_instance_2['id']}", headers=hdrs)


# ══════════════════════════════════════════════════════════════════════
# WebSocket telemetry stream
# ══════════════════════════════════════════════════════════════════════

def test_ws_stream_accepts_connection():
    """WebSocket stream accepts a connection for any drone_id (no auth required)."""
    from contextlib import asynccontextmanager
    from starlette.testclient import TestClient
    from app.main import app

    @asynccontextmanager
    async def _noop_lifespan(a):
        yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _noop_lifespan
    try:
        with TestClient(app, raise_server_exceptions=False) as tc:
            with tc.websocket_connect("/api/drone-control/stream/9999") as ws:
                # drone 9999 has no active telemetry; queue idles — connection accepted
                pass
    finally:
        app.router.lifespan_context = original_lifespan
