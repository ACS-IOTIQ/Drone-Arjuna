from unittest.mock import AsyncMock, patch

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


async def _create_mission(client: AsyncClient, headers: dict, drone_id: int | None = None) -> dict:
    resp = await client.post(
        "/api/flight/missions",
        json=mission_payload(drone_id),
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_mission_crud_summary_validation_simulation_and_delete(
    client: AsyncClient,
    admin_user,
    flight_controller_user,
    viewer_user,
    make_token,
):
    admin_headers = auth_headers(admin_user, make_token)
    fc_headers = auth_headers(flight_controller_user, make_token)
    viewer_headers = auth_headers(viewer_user, make_token)
    drone = await _seed_drone(client, admin_headers)
    mission = await _create_mission(client, fc_headers, drone["id"])
    mid = mission["id"]
    assert mission["created_by"] == flight_controller_user.id
    assert len(mission["waypoints"]) == 2

    list_resp = await client.get("/api/flight/missions", headers=viewer_headers)
    assert list_resp.status_code == 200
    assert any(item["id"] == mid for item in list_resp.json())

    get_resp = await client.get(f"/api/flight/missions/{mid}", headers=viewer_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == mission["name"]

    summary = await client.get(f"/api/flight/missions/{mid}/summary", headers=viewer_headers)
    assert summary.status_code == 200
    assert summary.json()["waypoint_count"] == 2
    assert summary.json()["total_distance_km"] > 0

    validate = await client.post(f"/api/flight/missions/{mid}/validate", headers=fc_headers)
    assert validate.status_code == 200
    assert validate.json()["valid"] is True

    simulate = await client.get(f"/api/flight/missions/{mid}/simulate", headers=viewer_headers)
    assert simulate.status_code == 200
    assert simulate.json()["mission_id"] == mid
    assert simulate.json()["frame_count"] > 0

    viewer_status = await client.patch(
        f"/api/flight/missions/{mid}/status",
        json={"status": "approved"},
        headers=viewer_headers,
    )
    assert viewer_status.status_code == 403

    status_resp = await client.patch(
        f"/api/flight/missions/{mid}/status",
        json={"status": "completed"},
        headers=admin_headers,
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "completed"

    delete_resp = await client.delete(f"/api/flight/missions/{mid}", headers=fc_headers)
    assert delete_resp.status_code == 204

    missing = await client.get(f"/api/flight/missions/{mid}", headers=viewer_headers)
    assert missing.status_code == 404


async def test_mission_create_validation_and_empty_mission_failures(
    client: AsyncClient, flight_controller_user, viewer_user, make_token
):
    fc_headers = auth_headers(flight_controller_user, make_token)
    viewer_headers = auth_headers(viewer_user, make_token)

    blank = await client.post(
        "/api/flight/missions",
        json=mission_payload(name="   "),
        headers=fc_headers,
    )
    assert blank.status_code == 422

    duplicate_wp = mission_payload(
        waypoints=[
            {"sequence": 1, "latitude": 12.9, "longitude": 80.1, "altitude_m": 10},
            {"sequence": 1, "latitude": 12.91, "longitude": 80.11, "altitude_m": 20},
        ]
    )
    duplicate = await client.post(
        "/api/flight/missions",
        json=duplicate_wp,
        headers=fc_headers,
    )
    assert duplicate.status_code == 422

    empty = await client.post(
        "/api/flight/missions",
        json=mission_payload(waypoints=[]),
        headers=fc_headers,
    )
    assert empty.status_code == 201
    mid = empty.json()["id"]

    summary = await client.get(f"/api/flight/missions/{mid}/summary", headers=viewer_headers)
    assert summary.status_code == 400

    simulate = await client.get(f"/api/flight/missions/{mid}/simulate", headers=viewer_headers)
    assert simulate.status_code == 400

    validate = await client.post(f"/api/flight/missions/{mid}/validate", headers=fc_headers)
    assert validate.status_code == 200
    assert validate.json()["valid"] is False


async def test_mission_upload_returns_service_error_when_drone_not_connected(
    client: AsyncClient, admin_user, flight_controller_user, make_token
):
    admin_headers = auth_headers(admin_user, make_token)
    fc_headers = auth_headers(flight_controller_user, make_token)
    drone = await _seed_drone(client, admin_headers)
    mission = await _create_mission(client, fc_headers, drone["id"])

    upload = await client.post(
        f"/api/flight/missions/{mission['id']}/upload",
        headers=fc_headers,
    )
    assert upload.status_code == 503


async def test_delete_executing_mission_is_blocked(
    client: AsyncClient, admin_user, flight_controller_user, make_token
):
    admin_headers = auth_headers(admin_user, make_token)
    fc_headers = auth_headers(flight_controller_user, make_token)
    mission = await _create_mission(client, fc_headers)

    status_resp = await client.patch(
        f"/api/flight/missions/{mission['id']}/status",
        json={"status": "executing"},
        headers=admin_headers,
    )
    assert status_resp.status_code == 200

    delete_resp = await client.delete(
        f"/api/flight/missions/{mission['id']}",
        headers=fc_headers,
    )
    assert delete_resp.status_code == 409


async def test_survey_grid_generation_and_invalid_body(
    client: AsyncClient, flight_controller_user, make_token
):
    headers = auth_headers(flight_controller_user, make_token)
    resp = await client.post(
        "/api/flight/survey-grid",
        json={
            "polygon": [[12.9, 80.1], [12.9, 80.102], [12.902, 80.102], [12.902, 80.1]],
            "altitude_m": 60,
            "spacing_m": 100,
            "speed_ms": 10,
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == len(resp.json()["waypoints"])
    assert resp.json()["count"] > 0

    invalid = await client.post(
        "/api/flight/survey-grid",
        json={"altitude_m": 60},
        headers=headers,
    )
    assert invalid.status_code == 400
