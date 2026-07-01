"""
Geofence API tests
==================
Tests for the two new geofence integration points:

1. POST /api/drone-control/drones/{id}/geofence
   - Valid Polygon GeoJSON → 200, geofence_store populated
   - Valid MultiPolygon → 200
   - geofence: null → 200, fence cleared
   - Invalid GeoJSON → 422
   - VIEWER → 403 (requires FLIGHT_CONTROLLER+)
   - Unauthenticated → 401

2. Simulation start bridge
   POST /api/drone-control/simulate/start with a fenced mission loads the
   fence into geofence_store so breach detection is armed during simulation.
   - Mission WITH geofence → geofence_store populated for drone
   - Mission WITHOUT geofence → geofence_store not populated
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.tests.helpers import auth_headers

# ── Shared GeoJSON fixtures ────────────────────────────────────────────────────

_SQUARE = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
}

_MULTI = {
    "type": "MultiPolygon",
    "coordinates": [
        [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
        [[[5.0, 5.0], [6.0, 5.0], [6.0, 6.0], [5.0, 6.0], [5.0, 5.0]]],
    ],
}

# A DroneType body used by the simulation-bridge fixtures
_DT_BODY = {
    "name":                   "GF-API-Test-Type",
    "manufacturer":           "ACS Systems",
    "model":                  "GF-T1",
    "size_class":             "small",
    "mission_type":           "ISR",
    "is_vtol":                False,
    "max_speed_ms":           25.0,
    "cruise_speed_ms":        18.0,
    "max_altitude_m":         1000.0,
    "endurance_h":            2.0,
    "range_km":               40.0,
    "max_takeoff_weight_kg":  5.0,
    "max_payload_weight_kg":  2.0,
    "autopilot_type":         "ArduPilot",
}

_HOME_WP = {
    "sequence":     1,
    "latitude":     0.2,
    "longitude":    0.2,
    "altitude_m":   0.0,
    "altitude_ref": "AGL",
    "action":       "none",
    "is_home":      True,
}
_TARGET_WP = {
    "sequence":     2,
    "latitude":     0.5,
    "longitude":    0.5,
    "altitude_m":   50.0,
    "altitude_ref": "AGL",
    "action":       "none",
}

# Arbitrary drone_id used by the pure endpoint tests (no DB entity needed)
_TEST_DRONE_ID = 1


# ── Store cleanup ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_test_geofence():
    """Clear the fixed test drone_id from geofence_store before/after each test."""
    from app.utils.geofence import geofence_store
    geofence_store.clear(_TEST_DRONE_ID)
    yield
    geofence_store.clear(_TEST_DRONE_ID)


# ── Fixtures for simulation-bridge tests ──────────────────────────────────────

@pytest_asyncio.fixture
async def drone_type(client: AsyncClient, admin_user, make_token):
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.post("/api/master/drone-types", json=_DT_BODY, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/master/drone-types/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def drone_instance(client: AsyncClient, admin_user, drone_type, make_token):
    hdrs = auth_headers(admin_user, make_token)
    body = {
        "call_sign":     "GF-API-DRONE-01",
        "serial_number": "GF-SN-001",
        "drone_type_id": drone_type["id"],
    }
    resp = await client.post("/api/master/drones", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    yield resp.json()


# ═══════════════════════════════════════════════════════════════════════
# 1. POST /api/drone-control/drones/{id}/geofence
# ═══════════════════════════════════════════════════════════════════════

async def test_set_geofence_polygon_200(
    client: AsyncClient, flight_controller_user, make_token
):
    """Valid Polygon GeoJSON → 200, geofence_store populated for that drone."""
    from app.utils.geofence import geofence_store
    hdrs = auth_headers(flight_controller_user, make_token)

    resp = await client.post(
        f"/api/drone-control/drones/{_TEST_DRONE_ID}/geofence",
        json={"geofence": _SQUARE},
        headers=hdrs,
    )
    assert resp.status_code == 200
    assert resp.json()["drone_id"] == _TEST_DRONE_ID
    assert geofence_store.has_fence(_TEST_DRONE_ID)
    assert geofence_store.is_inside(_TEST_DRONE_ID, lat=0.5, lon=0.5) is True
    assert geofence_store.is_inside(_TEST_DRONE_ID, lat=2.0, lon=0.5) is False


async def test_set_geofence_multipolygon_200(
    client: AsyncClient, flight_controller_user, make_token
):
    """MultiPolygon is also accepted."""
    from app.utils.geofence import geofence_store
    hdrs = auth_headers(flight_controller_user, make_token)

    resp = await client.post(
        f"/api/drone-control/drones/{_TEST_DRONE_ID}/geofence",
        json={"geofence": _MULTI},
        headers=hdrs,
    )
    assert resp.status_code == 200
    assert geofence_store.has_fence(_TEST_DRONE_ID)
    # Both patches should be active
    assert geofence_store.is_inside(_TEST_DRONE_ID, lat=0.5, lon=0.5) is True
    assert geofence_store.is_inside(_TEST_DRONE_ID, lat=5.5, lon=5.5) is True


async def test_clear_geofence_null_200(
    client: AsyncClient, flight_controller_user, make_token
):
    """Sending geofence: null clears an existing fence and returns 200."""
    from app.utils.geofence import geofence_store
    hdrs = auth_headers(flight_controller_user, make_token)

    # First set a fence
    await client.post(
        f"/api/drone-control/drones/{_TEST_DRONE_ID}/geofence",
        json={"geofence": _SQUARE},
        headers=hdrs,
    )
    assert geofence_store.has_fence(_TEST_DRONE_ID)

    # Now clear it
    resp = await client.post(
        f"/api/drone-control/drones/{_TEST_DRONE_ID}/geofence",
        json={"geofence": None},
        headers=hdrs,
    )
    assert resp.status_code == 200
    assert "cleared" in resp.json()["detail"].lower()
    assert not geofence_store.has_fence(_TEST_DRONE_ID)


async def test_set_geofence_invalid_geojson_422(
    client: AsyncClient, flight_controller_user, make_token
):
    """Invalid GeoJSON geometry type → 422."""
    hdrs = auth_headers(flight_controller_user, make_token)
    resp = await client.post(
        f"/api/drone-control/drones/{_TEST_DRONE_ID}/geofence",
        json={"geofence": {"type": "NotAGeometry", "coordinates": []}},
        headers=hdrs,
    )
    assert resp.status_code == 422


async def test_set_geofence_missing_coords_422(
    client: AsyncClient, flight_controller_user, make_token
):
    """Polygon with no coordinates key → 422."""
    hdrs = auth_headers(flight_controller_user, make_token)
    resp = await client.post(
        f"/api/drone-control/drones/{_TEST_DRONE_ID}/geofence",
        json={"geofence": {"type": "Polygon"}},
        headers=hdrs,
    )
    assert resp.status_code == 422


async def test_set_geofence_viewer_403(
    client: AsyncClient, viewer_user, make_token
):
    """VIEWER role must receive 403 — endpoint requires FLIGHT_CONTROLLER+."""
    hdrs = auth_headers(viewer_user, make_token)
    resp = await client.post(
        f"/api/drone-control/drones/{_TEST_DRONE_ID}/geofence",
        json={"geofence": _SQUARE},
        headers=hdrs,
    )
    assert resp.status_code == 403


async def test_set_geofence_unauthenticated_401(client: AsyncClient):
    """No Bearer token → 401."""
    resp = await client.post(
        f"/api/drone-control/drones/{_TEST_DRONE_ID}/geofence",
        json={"geofence": _SQUARE},
    )
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════
# 2. Simulation start bridge
# ═══════════════════════════════════════════════════════════════════════

async def test_simulation_start_with_geofence_loads_store(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """
    Starting a simulation for a mission that carries a geofence must
    populate geofence_store for the assigned drone so breach detection
    is active from the first position tick.
    """
    from app.utils.geofence import geofence_store
    hdrs = auth_headers(flight_controller_user, make_token)
    drone_id = drone_instance["id"]

    # Create a mission with the square geofence.
    # Both waypoints are inside the fence so mission validation passes.
    mission_body = {
        "name":              "GF-Sim-Bridge-Test",
        "mission_type":      "ISR",
        "drone_instance_id": drone_id,
        "geofence":          _SQUARE,
        "waypoints":         [_HOME_WP, _TARGET_WP],
    }
    create = await client.post("/api/flight/missions", json=mission_body, headers=hdrs)
    assert create.status_code == 201, create.text
    mission = create.json()

    try:
        assert not geofence_store.has_fence(drone_id), "Store must start empty"

        sim = await client.post(
            "/api/drone-control/simulate/start",
            json={"mission_id": mission["id"]},
            headers=hdrs,
        )
        assert sim.status_code == 201, sim.text

        # Fence must now be active for this drone
        assert geofence_store.has_fence(drone_id)
        # Verify geometry: waypoints at (0.2, 0.2) and (0.5, 0.5) are inside
        assert geofence_store.is_inside(drone_id, lat=0.5, lon=0.5) is True
        # A point well outside the square must be detected as outside
        assert geofence_store.is_inside(drone_id, lat=5.0, lon=5.0) is False
    finally:
        await client.delete("/api/drone-control/simulate/stop", headers=hdrs)
        await client.delete(f"/api/flight/missions/{mission['id']}", headers=hdrs)
        geofence_store.clear(drone_id)


async def test_simulation_start_without_geofence_leaves_store_empty(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """
    A mission with no geofence must NOT populate geofence_store —
    breach detection should remain inactive.
    """
    from app.utils.geofence import geofence_store
    hdrs = auth_headers(flight_controller_user, make_token)
    drone_id = drone_instance["id"]

    mission_body = {
        "name":              "GF-Sim-NoFence-Test",
        "mission_type":      "ISR",
        "drone_instance_id": drone_id,
        # no "geofence" key
        "waypoints":         [_HOME_WP, _TARGET_WP],
    }
    create = await client.post("/api/flight/missions", json=mission_body, headers=hdrs)
    assert create.status_code == 201, create.text
    mission = create.json()

    try:
        sim = await client.post(
            "/api/drone-control/simulate/start",
            json={"mission_id": mission["id"]},
            headers=hdrs,
        )
        assert sim.status_code == 201, sim.text

        assert not geofence_store.has_fence(drone_id)
    finally:
        await client.delete("/api/drone-control/simulate/stop", headers=hdrs)
        await client.delete(f"/api/flight/missions/{mission['id']}", headers=hdrs)
        geofence_store.clear(drone_id)
