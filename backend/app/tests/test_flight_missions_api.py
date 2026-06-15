<<<<<<< HEAD
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
=======
"""
Flight / Missions API tests
============================
GET / POST / PATCH / DELETE /api/flight/missions
GET /api/flight/missions/{mid}/summary
POST /api/flight/missions/{mid}/validate
POST /api/flight/survey-grid

Covers:
  - Happy-path create / list / get / status-patch / delete
  - Creating mission with waypoints; summary computation
  - Duplicate sequence numbers → 422 (schema validator)
  - Blank mission name → 422
  - Delete executing mission → 409
  - Validate mission returns valid/errors/warnings dict
  - Survey-grid generates waypoints from a polygon
  - RBAC: VIEWER blocked from create/delete/validate/upload
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


_WP1 = {
    "sequence":    1,
    "latitude":    12.9716,
    "longitude":   77.5946,
    "altitude_m":  100.0,
    "altitude_ref": "AGL",
    "action":      "none",
}
_WP2 = {
    "sequence":    2,
    "latitude":    12.9800,
    "longitude":   77.6000,
    "altitude_m":  100.0,
    "altitude_ref": "AGL",
    "action":      "none",
}
_WP3 = {
    "sequence":    3,
    "latitude":    12.9850,
    "longitude":   77.5800,
    "altitude_m":  50.0,
    "altitude_ref": "AGL",
    "action":      "none",
}

_MISSION_BODY = {
    "name":         "Test Mission Alpha",
    "description":  "Automated test mission",
    "mission_type": "ISR",
    "waypoints":    [_WP1, _WP2, _WP3],
}

_MISSION_EMPTY_WPS = {
    "name":         "Test Mission No WPs",
    "mission_type": "Patrol",
    "waypoints":    [],
}


@pytest_asyncio.fixture
async def mission(client: AsyncClient, flight_controller_user, make_token):
    """Creates a mission with 3 waypoints, deletes after test."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.post("/api/flight/missions", json=_MISSION_BODY, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data  = resp.json()
    yield data
    # Teardown: only delete if still exists and not executing
    get = await client.get(f"/api/flight/missions/{data['id']}", headers=hdrs)
    if get.status_code == 200 and get.json().get("status") != "executing":
        await client.delete(f"/api/flight/missions/{data['id']}", headers=hdrs)


# ══════════════════════════════════════════════════════════════════════
# Create
# ══════════════════════════════════════════════════════════════════════

async def test_create_mission_with_waypoints_201(
    client: AsyncClient, flight_controller_user, make_token
):
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.post("/api/flight/missions", json=_MISSION_BODY, headers=hdrs)
    assert resp.status_code == 201
    body  = resp.json()
    assert body["name"]     == "Test Mission Alpha"
    assert body["status"]   == "planning"
    assert len(body["waypoints"]) == 3
    assert "id"         in body
    assert "created_at" in body
    await client.delete(f"/api/flight/missions/{body['id']}", headers=hdrs)


async def test_create_mission_no_waypoints_201(
    client: AsyncClient, flight_controller_user, make_token
):
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.post(
        "/api/flight/missions", json=_MISSION_EMPTY_WPS, headers=hdrs
    )
    assert resp.status_code == 201
    assert resp.json()["waypoints"] == []
    await client.delete(
        f"/api/flight/missions/{resp.json()['id']}", headers=hdrs
    )


async def test_create_mission_blank_name_422(
    client: AsyncClient, flight_controller_user, make_token
):
    """Blank mission name must be rejected by the schema validator."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.post(
        "/api/flight/missions",
        json={**_MISSION_BODY, "name": "   "},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_create_mission_duplicate_sequence_422(
    client: AsyncClient, flight_controller_user, make_token
):
    """Duplicate waypoint sequence numbers within a mission must return 422."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    dup_wps = [_WP1, {**_WP2, "sequence": 1}]  # sequence 1 used twice
    resp  = await client.post(
        "/api/flight/missions",
        json={**_MISSION_BODY, "waypoints": dup_wps},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# Read
# ══════════════════════════════════════════════════════════════════════

async def test_list_missions_200(
    client: AsyncClient, viewer_user, mission, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/flight/missions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert mission["id"] in [m["id"] for m in resp.json()]


async def test_get_mission_200(
    client: AsyncClient, viewer_user, mission, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        f"/api/flight/missions/{mission['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"]            == "Test Mission Alpha"
    assert len(body["waypoints"])  == 3


async def test_get_mission_not_found_404(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/flight/missions/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════

async def test_mission_summary_200(
    client: AsyncClient, viewer_user, mission, make_token
):
    """Summary returns distance / time / battery estimates for a mission with waypoints."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        f"/api/flight/missions/{mission['id']}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "total_distance_km"       in body
    assert "estimated_flight_time_min" in body
    assert "waypoint_count"          in body
    assert body["waypoint_count"]    == 3


async def test_mission_summary_no_waypoints_400(
    client: AsyncClient, viewer_user, flight_controller_user, make_token
):
    """Summary on a mission with no waypoints must return 400."""
    fc_token  = make_token(flight_controller_user.id, flight_controller_user.role)
    fc_hdrs   = {"Authorization": f"Bearer {fc_token}"}
    create = await client.post(
        "/api/flight/missions", json=_MISSION_EMPTY_WPS, headers=fc_hdrs
    )
    assert create.status_code == 201
    mid = create.json()["id"]

    vw_token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/flight/missions/{mid}/summary",
        headers={"Authorization": f"Bearer {vw_token}"},
    )
    assert resp.status_code == 400

    await client.delete(f"/api/flight/missions/{mid}", headers=fc_hdrs)


# ══════════════════════════════════════════════════════════════════════
# Status patch
# ══════════════════════════════════════════════════════════════════════

async def test_patch_mission_status_200(
    client: AsyncClient, admin_user, mission, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.patch(
        f"/api/flight/missions/{mission['id']}/status",
        json={"status": "approved"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


async def test_patch_mission_status_flight_controller_403(
    client: AsyncClient, flight_controller_user, mission, make_token
):
    """FLIGHT_CONTROLLER is below MISSION_COMMANDER — must be blocked."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.patch(
        f"/api/flight/missions/{mission['id']}/status",
        json={"status": "approved"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# Delete
# ══════════════════════════════════════════════════════════════════════

async def test_delete_mission_204(
    client: AsyncClient, flight_controller_user, make_token
):
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    create = await client.post(
        "/api/flight/missions", json=_MISSION_EMPTY_WPS, headers=hdrs
    )
    assert create.status_code == 201
    mid = create.json()["id"]

    delete = await client.delete(f"/api/flight/missions/{mid}", headers=hdrs)
    assert delete.status_code == 204

    get = await client.get(f"/api/flight/missions/{mid}", headers=hdrs)
    assert get.status_code == 404


async def test_delete_executing_mission_409(
    client: AsyncClient, admin_user, flight_controller_user, make_token
):
    """Deleting a mission whose status is 'executing' must return 409."""
    fc_token = make_token(flight_controller_user.id, flight_controller_user.role)
    fc_hdrs  = {"Authorization": f"Bearer {fc_token}"}
    ad_token = make_token(admin_user.id, admin_user.role)
    ad_hdrs  = {"Authorization": f"Bearer {ad_token}"}

    create = await client.post(
        "/api/flight/missions", json=_MISSION_EMPTY_WPS, headers=fc_hdrs
    )
    assert create.status_code == 201
    mid = create.json()["id"]

    # Promote to executing via mission_commander (admin)
    await client.patch(
        f"/api/flight/missions/{mid}/status",
        json={"status": "executing"},
        headers=ad_hdrs,
    )

    # Attempt to delete — blocked
    resp = await client.delete(f"/api/flight/missions/{mid}", headers=fc_hdrs)
    assert resp.status_code == 409

    # Cleanup: abort then delete
    await client.patch(
        f"/api/flight/missions/{mid}/status",
        json={"status": "aborted"},
        headers=ad_hdrs,
    )
    await client.delete(f"/api/flight/missions/{mid}", headers=fc_hdrs)


# ══════════════════════════════════════════════════════════════════════
# Validate
# ══════════════════════════════════════════════════════════════════════

async def test_validate_mission_200(
    client: AsyncClient, flight_controller_user, mission, make_token
):
    """Validate returns a {valid, errors, warnings} dict."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.post(
        f"/api/flight/missions/{mission['id']}/validate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "valid"    in body
    assert "errors"   in body
    assert "warnings" in body


async def test_validate_mission_not_found_404(
    client: AsyncClient, flight_controller_user, make_token
):
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.post(
        "/api/flight/missions/999999/validate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# Survey grid
# ══════════════════════════════════════════════════════════════════════

async def test_survey_grid_200(
    client: AsyncClient, flight_controller_user, make_token
):
    """Survey grid generates lawnmower waypoints from a polygon."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    body  = {
        "polygon": [
            [12.97, 77.59],
            [12.97, 77.61],
            [12.99, 77.61],
            [12.99, 77.59],
        ],
        "altitude_m": 80.0,
        "spacing_m":  100.0,
        "speed_ms":   12.0,
    }
    resp = await client.post(
        "/api/flight/survey-grid",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert "waypoints" in result
    assert "count"     in result
    assert result["count"] > 0


async def test_survey_grid_missing_polygon_400(
    client: AsyncClient, flight_controller_user, make_token
):
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.post(
        "/api/flight/survey-grid",
        json={"altitude_m": 80.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


# ══════════════════════════════════════════════════════════════════════
# RBAC
# ══════════════════════════════════════════════════════════════════════

async def test_missions_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/flight/missions")
    assert resp.status_code == 401


async def test_viewer_blocked_from_create_mission_403(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        "/api/flight/missions",
        json=_MISSION_BODY,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_viewer_blocked_from_delete_mission_403(
    client: AsyncClient, viewer_user, mission, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.delete(
        f"/api/flight/missions/{mission['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_viewer_blocked_from_validate_403(
    client: AsyncClient, viewer_user, mission, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        f"/api/flight/missions/{mission['id']}/validate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
>>>>>>> origin/master
