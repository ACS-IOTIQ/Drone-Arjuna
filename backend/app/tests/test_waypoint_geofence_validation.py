"""
Waypoint & geofence validation gap-fill tests
==============================================
Covers cases identified as missing from the existing geofence/mission
test suites (test_geofence_api.py, test_flight_missions_api.py):

  1. GET /api/drone-control/drones/{id}/geofence  (read endpoint — was untested)
       - no fence set → 200, geofence: null
       - fence set → 200, geofence echoes back the stored GeoJSON
       - unauthenticated → 401

  2. Waypoint coordinate bounds on mission create
       - latitude out of [-90, 90] → 422
       - longitude out of [-180, 180] → 422

  3. Duplicate waypoint sequence numbers on mission create → 422

  4. Degenerate geofence polygon (fewer than 3 distinct vertices) → 422
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.tests.helpers import auth_headers

_TEST_DRONE_ID = 2001

_VALID_WP_1 = {
    "sequence":     1,
    "latitude":     12.9716,
    "longitude":    77.5946,
    "altitude_m":   0.0,
    "altitude_ref": "AGL",
    "action":       "none",
    "is_home":      True,
}
_VALID_WP_2 = {
    "sequence":     2,
    "latitude":     12.9800,
    "longitude":    77.6000,
    "altitude_m":   80.0,
    "altitude_ref": "AGL",
    "action":       "none",
}


@pytest.fixture(autouse=True)
def clean_test_geofence():
    from app.utils.geofence import geofence_store
    geofence_store.clear(_TEST_DRONE_ID)
    yield
    geofence_store.clear(_TEST_DRONE_ID)


# ═══════════════════════════════════════════════════════════════════════
# 1. GET /api/drone-control/drones/{id}/geofence
# ═══════════════════════════════════════════════════════════════════════

async def test_get_geofence_no_fence_returns_null(
    client: AsyncClient, viewer_user, make_token
):
    hdrs = auth_headers(viewer_user, make_token)
    resp = await client.get(
        f"/api/drone-control/drones/{_TEST_DRONE_ID}/geofence", headers=hdrs
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["drone_id"] == _TEST_DRONE_ID
    assert body["geofence"] is None


async def test_get_geofence_echoes_stored_fence(
    client: AsyncClient, flight_controller_user, viewer_user, make_token
):
    square = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
    }
    setter_hdrs = auth_headers(flight_controller_user, make_token)
    set_resp = await client.post(
        f"/api/drone-control/drones/{_TEST_DRONE_ID}/geofence",
        json={"geofence": square},
        headers=setter_hdrs,
    )
    assert set_resp.status_code == 200

    reader_hdrs = auth_headers(viewer_user, make_token)
    resp = await client.get(
        f"/api/drone-control/drones/{_TEST_DRONE_ID}/geofence", headers=reader_hdrs
    )
    assert resp.status_code == 200
    assert resp.json()["geofence"] is not None


async def test_get_geofence_unauthenticated_401(client: AsyncClient):
    resp = await client.get(f"/api/drone-control/drones/{_TEST_DRONE_ID}/geofence")
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════
# 2. Waypoint coordinate bounds
# ═══════════════════════════════════════════════════════════════════════

async def test_mission_create_latitude_out_of_range_422(
    client: AsyncClient, flight_controller_user, make_token
):
    hdrs = auth_headers(flight_controller_user, make_token)
    bad_wp = {**_VALID_WP_1, "latitude": 91.0}
    resp = await client.post(
        "/api/flight/missions",
        json={"name": "Bad-Lat-Mission", "mission_type": "ISR", "waypoints": [bad_wp]},
        headers=hdrs,
    )
    assert resp.status_code == 422


async def test_mission_create_longitude_out_of_range_422(
    client: AsyncClient, flight_controller_user, make_token
):
    hdrs = auth_headers(flight_controller_user, make_token)
    bad_wp = {**_VALID_WP_1, "longitude": -181.0}
    resp = await client.post(
        "/api/flight/missions",
        json={"name": "Bad-Lon-Mission", "mission_type": "ISR", "waypoints": [bad_wp]},
        headers=hdrs,
    )
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════
# 3. Duplicate waypoint sequence numbers
# ═══════════════════════════════════════════════════════════════════════

async def test_mission_create_duplicate_sequence_422(
    client: AsyncClient, flight_controller_user, make_token
):
    hdrs = auth_headers(flight_controller_user, make_token)
    dup_wp = {**_VALID_WP_2, "sequence": _VALID_WP_1["sequence"]}
    resp = await client.post(
        "/api/flight/missions",
        json={
            "name": "Dup-Seq-Mission",
            "mission_type": "ISR",
            "waypoints": [_VALID_WP_1, dup_wp],
        },
        headers=hdrs,
    )
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════
# 4. Degenerate geofence polygon
# ═══════════════════════════════════════════════════════════════════════

async def test_set_geofence_degenerate_polygon_422(
    client: AsyncClient, flight_controller_user, make_token
):
    """A polygon ring with fewer than 3 distinct vertices is geometrically invalid."""
    hdrs = auth_headers(flight_controller_user, make_token)
    degenerate = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [0.0, 0.0]]],
    }
    resp = await client.post(
        f"/api/drone-control/drones/{_TEST_DRONE_ID}/geofence",
        json={"geofence": degenerate},
        headers=hdrs,
    )
    assert resp.status_code == 422
