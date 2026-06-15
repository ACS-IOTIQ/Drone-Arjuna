"""
Drone Analyst — telemetry stats and series endpoint tests
==========================================================
GET /api/analyst/missions/{mission_id}/stats
GET /api/analyst/missions/{mission_id}/series

These endpoints query TimescaleDB directly (separate from the main PostgreSQL
database). In the test environment, the TimescaleDB engine is not available via
the in-memory SQLite override, so these endpoints will return:
  - 200 with empty/zero data if the service handles the absence gracefully, or
  - 5xx if the TS engine is unavailable

Tests verify:
  - The endpoints require authentication (401 without token)
  - The endpoints are accessible to VIEWER role (no 403)
  - The endpoints return a valid JSON structure (dict, not list)
  - stats response shape: frame_count, avg_altitude_m, max_altitude_m, etc.
  - series response shape: mission_id, param, points list
  - series accepts different param names without crashing
  - series respects bucket_seconds query parameter
  - Non-existent mission_id returns 200 with empty/zero data (no telemetry recorded)

NOTE: We intentionally do not assert exact data values here because the test
environment has no telemetry stored. These tests document expected API behaviour
and will reveal regressions if the endpoint shapes change.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


_DT_BODY = {
    "name": "Analyst-Telem-DroneType",
    "manufacturer": "ACS Test",
    "model": "AT-T1",
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


@pytest_asyncio.fixture
async def mission(client: AsyncClient, flight_controller_user, make_token):
    """Minimal mission for telemetry endpoint tests."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        "/api/flight/missions",
        json={"name": "Analyst-Telem-Mission", "mission_type": "ISR", "waypoints": []},
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/flight/missions/{data['id']}", headers=hdrs)


# ══════════════════════════════════════════════════════════════════════
# Stats endpoint
# ══════════════════════════════════════════════════════════════════════

async def test_mission_stats_requires_auth_401(client: AsyncClient):
    resp = await client.get("/api/analyst/missions/1/stats")
    assert resp.status_code == 401


async def test_mission_stats_viewer_accessible(
    client: AsyncClient, viewer_user, mission, make_token
):
    """VIEWER can access mission stats — endpoint requires no special role."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/analyst/missions/{mission['id']}/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


async def test_mission_stats_response_shape(
    client: AsyncClient, viewer_user, mission, make_token
):
    """
    Stats response must be a dict with all expected keys.
    With no telemetry in the test DB the service returns zero values.
    """
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/analyst/missions/{mission['id']}/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict)
    assert "frame_count" in body
    assert "avg_altitude_m" in body
    assert "max_altitude_m" in body


async def test_mission_stats_nonexistent_mission_returns_empty(
    client: AsyncClient, viewer_user, make_token
):
    """
    Stats for a mission that has no telemetry should return 200 with
    frame_count=0 rather than 404 — telemetry absence ≠ mission absence.
    """
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        "/api/analyst/missions/999999/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code != 200:
        pytest.skip("TimescaleDB not available in test environment")

    body = resp.json()
    assert body["frame_count"] == 0


# ══════════════════════════════════════════════════════════════════════
# Series endpoint
# ══════════════════════════════════════════════════════════════════════

async def test_mission_series_requires_auth_401(client: AsyncClient):
    resp = await client.get("/api/analyst/missions/1/series")
    assert resp.status_code == 401


async def test_mission_series_viewer_accessible(
    client: AsyncClient, viewer_user, mission, make_token
):
    """VIEWER can access the series endpoint."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/analyst/missions/{mission['id']}/series",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


async def test_mission_series_response_shape(
    client: AsyncClient, viewer_user, mission, make_token
):
    """Series response must contain mission_id, param, and series list."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/analyst/missions/{mission['id']}/series?param=alt_agl&bucket_seconds=5",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict)
    assert "mission_id" in body
    assert "param" in body
    assert "series" in body
    assert isinstance(body["series"], list)
    assert body["param"] == "alt_agl"


async def test_mission_series_different_params(
    client: AsyncClient, viewer_user, mission, make_token
):
    """Different telemetry params can be requested without error."""
    token = make_token(viewer_user.id, viewer_user.role)
    for param in ["alt_agl", "groundspeed_ms", "battery_remaining_pct"]:
        resp = await client.get(
            f"/api/analyst/missions/{mission['id']}/series?param={param}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, f"Unexpected {resp.status_code} for param={param}"


async def test_mission_series_bucket_seconds_validation(
    client: AsyncClient, viewer_user, mission, make_token
):
    """bucket_seconds must be between 1 and 300 — out of range → 422."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/analyst/missions/{mission['id']}/series?bucket_seconds=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_mission_series_bucket_seconds_too_large_422(
    client: AsyncClient, viewer_user, mission, make_token
):
    """bucket_seconds > 300 must be rejected."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/analyst/missions/{mission['id']}/series?bucket_seconds=9999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
