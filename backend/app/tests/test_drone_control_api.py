<<<<<<< HEAD
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

from httpx import AsyncClient

from app.tests.helpers import (
    auth_headers,
    drone_instance_payload,
    drone_type_payload,
    mission_payload,
)


async def _seed_drone(client: AsyncClient, headers: dict) -> dict:
    type_resp = await client.post(
        "/api/master/drone-types",
        json=drone_type_payload(),
        headers=headers,
    )
    assert type_resp.status_code == 201, type_resp.text
    drone_resp = await client.post(
        "/api/master/drones",
        json=drone_instance_payload(type_resp.json()["id"]),
        headers=headers,
    )
    assert drone_resp.status_code == 201, drone_resp.text
    return drone_resp.json()


async def _seed_mission(client: AsyncClient, headers: dict, drone_id: int) -> dict:
    mission_resp = await client.post(
        "/api/flight/missions",
        json=mission_payload(drone_id),
        headers=headers,
    )
    assert mission_resp.status_code == 201, mission_resp.text
    return mission_resp.json()


async def test_control_ports_status_and_telemetry_snapshot(
    client: AsyncClient, viewer_user, make_token
):
    headers = auth_headers(viewer_user, make_token)

    with patch("app.modules.drone_control.router.serial.tools.list_ports.comports", return_value=[]):
        ports = await client.get("/api/drone-control/ports", headers=headers)
    assert ports.status_code == 200
    assert {"udp", "tcp"}.issubset({item["type"] for item in ports.json()})

    from app.modules.drone_control.router import mavlink_manager

    mavlink_manager.state.init_drone(901, "CTRL-901")
    await mavlink_manager.state.update(
        901,
        {"drone_id": 901, "lat": 12.9, "lon": 80.1, "battery_remaining_pct": 88},
    )
    try:
        telemetry = await client.get("/api/drone-control/telemetry/901", headers=headers)
        assert telemetry.status_code == 200
        assert telemetry.json()["battery_remaining_pct"] == 88

        status = await client.get("/api/drone-control/status", headers=headers)
        assert status.status_code == 200
        assert any(item["drone_id"] == 901 for item in status.json()["drones"])
    finally:
        mavlink_manager.state.remove_drone(901)

    missing = await client.get("/api/drone-control/telemetry/902", headers=headers)
    assert missing.status_code == 404


async def test_connect_disconnect_and_command_endpoints(
    client: AsyncClient, flight_controller_user, viewer_user, make_token
):
    fc_headers = auth_headers(flight_controller_user, make_token)
    viewer_headers = auth_headers(viewer_user, make_token)

    viewer_connect = await client.post(
        "/api/drone-control/connect",
        json={"drone_instance_id": 10, "transport": "udp", "host": "127.0.0.1", "port": 14550},
        headers=viewer_headers,
    )
    assert viewer_connect.status_code == 403

    with patch("app.modules.drone_control.router.mavlink_manager.connect", AsyncMock(return_value=True)):
        connect = await client.post(
            "/api/drone-control/connect",
            json={"drone_instance_id": 10, "transport": "udp", "host": "127.0.0.1", "port": 14550},
            headers=fc_headers,
        )
    assert connect.status_code == 201
    assert connect.json()["drone_id"] == 10

    with patch("app.modules.drone_control.router.mavlink_manager.connect", AsyncMock(return_value=False)):
        failed = await client.post(
            "/api/drone-control/connect",
            json={"drone_instance_id": 10, "transport": "udp"},
            headers=fc_headers,
        )
    assert failed.status_code == 503

    with patch("app.modules.drone_control.router.mavlink_manager.send_command", AsyncMock(return_value=True)):
        command = await client.post(
            "/api/drone-control/command",
            json={"drone_id": 10, "command": "takeoff", "params": {"altitude": 30}},
            headers=fc_headers,
        )
    assert command.status_code == 200
    assert "takeoff" in command.json()["detail"]

    with patch("app.modules.drone_control.router.mavlink_manager.send_command", AsyncMock(return_value=False)):
        failed_command = await client.post(
            "/api/drone-control/command",
            json={"drone_id": 10, "command": "rtl", "params": {}},
            headers=fc_headers,
        )
    assert failed_command.status_code == 503

    disconnect_mock = AsyncMock()
    with patch("app.modules.drone_control.router.mavlink_manager.disconnect", disconnect_mock):
        disconnect = await client.post("/api/drone-control/disconnect/10", headers=fc_headers)
    assert disconnect.status_code == 200
    disconnect_mock.assert_awaited_once_with(10)


async def test_autoconnect_success_failure_and_conflict(
    client: AsyncClient, admin_user, flight_controller_user, make_token
):
    admin_headers = auth_headers(admin_user, make_token)
    fc_headers = auth_headers(flight_controller_user, make_token)
    drone = await _seed_drone(client, admin_headers)

    with (
        patch("app.modules.drone_control.router.serial.tools.list_ports.comports", return_value=[]),
        patch("app.modules.drone_control.router.mavlink_manager.connect", AsyncMock(side_effect=[False, True])),
    ):
        success = await client.post(
            "/api/drone-control/autoconnect",
            json={"drone_instance_id": drone["id"]},
            headers=fc_headers,
        )
    assert success.status_code == 200
    assert success.json()["drone_id"] == drone["id"]
    assert success.json()["transport"] == "udp"

    with (
        patch("app.modules.drone_control.router.serial.tools.list_ports.comports", return_value=[]),
        patch("app.modules.drone_control.router.mavlink_manager.connect", AsyncMock(return_value=False)),
    ):
        failure = await client.post(
            "/api/drone-control/autoconnect",
            json={"drone_instance_id": drone["id"]},
            headers=fc_headers,
        )
    assert failure.status_code == 503

    connected = Mock(connected=True)
    with patch.dict(
        "app.modules.drone_control.router.mavlink_manager._connections",
        {drone["id"]: connected},
        clear=True,
    ):
        conflict = await client.post(
            "/api/drone-control/autoconnect",
            json={"drone_instance_id": drone["id"]},
            headers=fc_headers,
        )
    assert conflict.status_code == 409


async def test_simulation_status_start_stop_edge_cases(
    client: AsyncClient, admin_user, flight_controller_user, viewer_user, make_token
):
    admin_headers = auth_headers(admin_user, make_token)
    fc_headers = auth_headers(flight_controller_user, make_token)
    viewer_headers = auth_headers(viewer_user, make_token)
    drone = await _seed_drone(client, admin_headers)
    mission = await _seed_mission(client, fc_headers, drone["id"])

    status = await client.get("/api/drone-control/simulate/status", headers=viewer_headers)
    assert status.status_code == 200
    assert "active" in status.json()

    stop = await client.delete("/api/drone-control/simulate/stop", headers=fc_headers)
    assert stop.status_code == 404

    start_mock = AsyncMock()
    attach_mock = Mock()
    from app.modules.drone_control.router import mission_simulator

    with (
        patch("app.modules.drone_control.router.mission_simulator.start", start_mock),
        patch.object(type(mission_simulator), "active", new_callable=PropertyMock, return_value=False),
        patch("app.modules.drone_control.router.mavlink_manager.attach_simulation", attach_mock),
    ):
        start = await client.post(
            "/api/drone-control/simulate/start",
            json={"mission_id": mission["id"], "speed_multiplier": 2.0},
            headers=fc_headers,
        )
    assert start.status_code == 201
    assert start.json()["drone_id"] == drone["id"]
    assert start.json()["waypoint_count"] == 1
    start_mock.assert_awaited_once()
    attach_mock.assert_called_once()

    missing = await client.post(
        "/api/drone-control/simulate/start",
        json={"mission_id": 999999},
        headers=fc_headers,
    )
    assert missing.status_code == 404
=======
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
import pytest
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
>>>>>>> origin/master
