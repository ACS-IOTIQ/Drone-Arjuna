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
