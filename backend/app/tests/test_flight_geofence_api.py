"""
Geofence Violation Tests — no frontend, no SITL required
=========================================================
Tests the POST /api/flight/missions/{id}/validate endpoint to verify that
MissionValidator correctly detects waypoints outside a GeoJSON geofence.

How it works end-to-end:
  1. A GeoJSON Polygon is stored in mission.geofence when creating the mission
  2. POST /validate calls MissionPlanner.validate_mission()
  3. MissionValidator._check_geofence() runs point_in_polygon() (ray-casting)
     against every waypoint in the mission
  4. Violations produce an error: "Waypoint {seq} ({lat:.5f}, {lon:.5f})
     is outside the defined geofence"
  5. Malformed geofence → warning "Geofence format invalid — skipping geofence check"

GeoJSON coordinate order: [longitude, latitude]  ← opposite of waypoints
  geofence.coordinates:  [[lon, lat], ...]
  waypoints:             { "latitude": lat, "longitude": lon }

Test area: ~1 km² square near Bangalore
  SW corner: (12.965, 77.585)   NE corner: (12.975, 77.595)
  Inside :  lat=12.970, lon=77.590  (centre)
  Outside:  lat=13.000, lon=77.400  (far north-west)
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.tests.helpers import auth_headers


# ── Fixtures: drone type + instance needed for the upload test ─────────

_DT_BODY = {
    "name":                  "GF-Test-DroneType",
    "manufacturer":          "ACS Systems",
    "model":                 "GF-Alpha",
    "size_class":            "medium",
    "mission_type":          "ISR",
    "is_vtol":               True,
    "max_speed_ms":          30.0,
    "cruise_speed_ms":       20.0,
    "max_altitude_m":        500.0,
    "endurance_h":           4.0,
    "range_km":              100.0,
    "max_takeoff_weight_kg": 20.0,
    "max_payload_weight_kg": 5.0,
    "autopilot_type":        "ArduPilot",
}


@pytest_asyncio.fixture
async def gf_drone_type(client: AsyncClient, admin_user, make_token):
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.post("/api/master/drone-types", json=_DT_BODY, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/master/drone-types/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def gf_drone_instance(client: AsyncClient, admin_user, gf_drone_type, make_token):
    hdrs = auth_headers(admin_user, make_token)
    body = {
        "call_sign":     "GF-ALPHA-01",
        "serial_number": "GF-SN-001",
        "drone_type_id": gf_drone_type["id"],
    }
    resp = await client.post("/api/master/drones", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    yield resp.json()


# ── Shared geofence polygon ────────────────────────────────────────────
# GeoJSON Polygon — [lon, lat] order, ring must be closed (first == last)

_GEOFENCE = {
    "type": "Polygon",
    "coordinates": [[
        [77.585, 12.965],   # SW
        [77.595, 12.965],   # SE
        [77.595, 12.975],   # NE
        [77.585, 12.975],   # NW
        [77.585, 12.965],   # close ring → back to SW
    ]],
}

# ── Waypoint templates ─────────────────────────────────────────────────

_HOME_INSIDE = {
    "sequence":     1,
    "latitude":     12.970,
    "longitude":    77.590,
    "altitude_m":   0.0,
    "altitude_ref": "AGL",
    "action":       "none",
    "is_home":      True,
}

_WP_INSIDE = {
    "sequence":     2,
    "latitude":     12.972,
    "longitude":    77.592,
    "altitude_m":   50.0,
    "altitude_ref": "AGL",
    "action":       "none",
}

# lat=13.000 is 3 km north of the geofence boundary
# lon=77.400 is 20 km west of the geofence boundary
_WP_OUTSIDE = {
    "sequence":     2,
    "latitude":     13.000,
    "longitude":    77.400,
    "altitude_m":   50.0,
    "altitude_ref": "AGL",
    "action":       "none",
}

# Second violating waypoint for multi-violation test
_WP_OUTSIDE_2 = {
    "sequence":     3,
    "latitude":     12.900,
    "longitude":    77.700,
    "altitude_m":   80.0,
    "altitude_ref": "AGL",
    "action":       "photo",
}


# ── Helper ─────────────────────────────────────────────────────────────

async def _create_and_validate(
    client: AsyncClient,
    hdrs: dict,
    waypoints: list,
    geofence=_GEOFENCE,
    name: str = "GF-Test-Mission",
) -> tuple[int, dict]:
    """
    Creates a mission then immediately calls validate.
    Returns (mission_id, validate_response_dict).
    Caller must delete the mission in a try/finally block.
    """
    body: dict = {
        "name":         name,
        "mission_type": "ISR",
        "waypoints":    waypoints,
    }
    if geofence is not None:
        body["geofence"] = geofence

    create = await client.post("/api/flight/missions", json=body, headers=hdrs)
    assert create.status_code == 201, f"Mission create failed: {create.text}"

    mid = create.json()["id"]
    validate = await client.post(
        f"/api/flight/missions/{mid}/validate", headers=hdrs
    )
    assert validate.status_code == 200, f"Validate returned {validate.status_code}: {validate.text}"

    return mid, validate.json()


# ═══════════════════════════════════════════════════════════════════════
# Case 1 — All waypoints inside → no geofence errors
# ═══════════════════════════════════════════════════════════════════════

async def test_all_waypoints_inside_geofence_passes(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    Waypoints at (12.970, 77.590) and (12.972, 77.592) are both inside
    the geofence square. Validate must report no geofence errors.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    mid, result = await _create_and_validate(
        client, hdrs,
        waypoints=[_HOME_INSIDE, _WP_INSIDE],
    )
    try:
        gf_errors = [e for e in result["errors"] if "outside" in e.lower()]
        assert gf_errors == [], f"Unexpected geofence errors: {gf_errors}"
    finally:
        await client.delete(f"/api/flight/missions/{mid}", headers=hdrs)


# ═══════════════════════════════════════════════════════════════════════
# Case 2 — One waypoint outside → valid = false, error returned
# ═══════════════════════════════════════════════════════════════════════

async def test_waypoint_outside_geofence_returns_error(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    Waypoint 2 at (13.000, 77.400) is 3 km north and 20 km west of the
    geofence boundary. validate() must return valid=False and one error.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    mid, result = await _create_and_validate(
        client, hdrs,
        waypoints=[_HOME_INSIDE, _WP_OUTSIDE],
    )
    try:
        assert result["valid"] is False, "Expected valid=False when waypoint is outside geofence"
        gf_errors = [e for e in result["errors"] if "outside" in e.lower()]
        assert len(gf_errors) >= 1, f"Expected at least one geofence error, got: {result['errors']}"
    finally:
        await client.delete(f"/api/flight/missions/{mid}", headers=hdrs)


# ═══════════════════════════════════════════════════════════════════════
# Case 3 — Error message contains sequence number and coordinates
# ═══════════════════════════════════════════════════════════════════════

async def test_geofence_error_contains_sequence_and_coords(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    MissionValidator formats the error as:
      "Waypoint {seq} ({lat:.5f}, {lon:.5f}) is outside the defined geofence"
    The error must contain the violating waypoint's sequence, latitude,
    and longitude so the operator can identify the location immediately.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    mid, result = await _create_and_validate(
        client, hdrs,
        waypoints=[_HOME_INSIDE, _WP_OUTSIDE],
    )
    try:
        gf_errors = [e for e in result["errors"] if "outside" in e.lower()]
        assert gf_errors, "No geofence violation error found"

        err = gf_errors[0]
        assert "2" in err,         f"Waypoint sequence 2 not in error: {err}"
        assert "13.00000" in err,  f"Latitude 13.00000 not in error: {err}"
        assert "77.40000" in err,  f"Longitude 77.40000 not in error: {err}"
        assert "outside the defined geofence" in err, f"Expected full phrase in: {err}"
    finally:
        await client.delete(f"/api/flight/missions/{mid}", headers=hdrs)


# ═══════════════════════════════════════════════════════════════════════
# Case 4 — Multiple waypoints outside → all violations reported
# ═══════════════════════════════════════════════════════════════════════

async def test_multiple_waypoints_outside_all_reported(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    When two waypoints breach the geofence the validator must report a
    separate error for each one, not just stop at the first violation.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    outside_2 = {**_WP_OUTSIDE,   "sequence": 2}
    outside_3 = {**_WP_OUTSIDE_2, "sequence": 3}

    mid, result = await _create_and_validate(
        client, hdrs,
        waypoints=[_HOME_INSIDE, outside_2, outside_3],
    )
    try:
        assert result["valid"] is False
        gf_errors = [e for e in result["errors"] if "outside" in e.lower()]
        assert len(gf_errors) == 2, (
            f"Expected 2 geofence errors, got {len(gf_errors)}: {gf_errors}"
        )
        seqs_in_errors = {token for err in gf_errors for token in err.split() if token in ("2", "3")}
        assert "2" in seqs_in_errors, "Waypoint 2 violation not reported"
        assert "3" in seqs_in_errors, "Waypoint 3 violation not reported"
    finally:
        await client.delete(f"/api/flight/missions/{mid}", headers=hdrs)


# ═══════════════════════════════════════════════════════════════════════
# Case 5 — Home waypoint outside geofence is also caught
# ═══════════════════════════════════════════════════════════════════════

async def test_home_waypoint_outside_geofence_caught(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    The home/takeoff waypoint is not exempt from the geofence check.
    Launching from outside the geofence is a violation just like any
    other waypoint.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    home_outside = {**_HOME_INSIDE, "latitude": 13.100, "longitude": 77.200}

    mid, result = await _create_and_validate(
        client, hdrs,
        waypoints=[home_outside, _WP_INSIDE],
    )
    try:
        assert result["valid"] is False
        gf_errors = [e for e in result["errors"] if "outside" in e.lower()]
        assert len(gf_errors) >= 1, "Home waypoint outside geofence was not caught"
        assert "1" in gf_errors[0], f"Error should reference waypoint sequence 1: {gf_errors[0]}"
    finally:
        await client.delete(f"/api/flight/missions/{mid}", headers=hdrs)


# ═══════════════════════════════════════════════════════════════════════
# Case 6 — No geofence defined → check skipped, valid = true
# ═══════════════════════════════════════════════════════════════════════

async def test_no_geofence_check_skipped(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    When mission.geofence is None the validator skips the geofence check
    entirely — even with waypoints that would fail if a geofence were set.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    mid, result = await _create_and_validate(
        client, hdrs,
        waypoints=[_HOME_INSIDE, _WP_OUTSIDE],
        geofence=None,    # explicitly no geofence
    )
    try:
        gf_errors = [
            e for e in result["errors"]
            if "outside" in e.lower() or "geofence" in e.lower()
        ]
        assert gf_errors == [], (
            f"Should have no geofence errors when geofence=None: {gf_errors}"
        )
    finally:
        await client.delete(f"/api/flight/missions/{mid}", headers=hdrs)


# ═══════════════════════════════════════════════════════════════════════
# Case 7 — Malformed geofence → warning issued, no hard crash
# ═══════════════════════════════════════════════════════════════════════

async def test_malformed_geofence_warns_and_skips(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    A geofence dict missing the 'coordinates' key causes
    geojson_polygon_to_ring() to return None.
    MissionValidator._check_geofence() catches this and adds:
      "Geofence format invalid — skipping geofence check"
    No hard 'outside' errors should be raised.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    bad_geofence = {"type": "Polygon"}   # 'coordinates' key missing

    mid, result = await _create_and_validate(
        client, hdrs,
        waypoints=[_HOME_INSIDE, _WP_OUTSIDE],
        geofence=bad_geofence,
    )
    try:
        gf_warnings = [w for w in result["warnings"] if "geofence" in w.lower()]
        assert len(gf_warnings) >= 1, (
            f"Expected a geofence format warning, got warnings: {result['warnings']}"
        )
        assert "skipping" in gf_warnings[0].lower(), (
            f"Warning should mention 'skipping': {gf_warnings[0]}"
        )
        # No 'outside' hard errors — check was skipped, not failed
        outside_errors = [e for e in result["errors"] if "outside" in e.lower()]
        assert outside_errors == [], f"Unexpected outside errors: {outside_errors}"
    finally:
        await client.delete(f"/api/flight/missions/{mid}", headers=hdrs)


# ═══════════════════════════════════════════════════════════════════════
# Case 8 — upload also runs geofence check before MAVLink (422)
# ═══════════════════════════════════════════════════════════════════════

async def test_upload_with_geofence_violation_returns_422(
    client: AsyncClient, flight_controller_user, gf_drone_instance, make_token
):
    """
    POST /upload runs validate_mission() BEFORE the MAVLink connection check.
    Check order in upload_to_drone():
      1. drone_instance_id present? → yes (we assign one)
      2. validate_mission() → geofence violation → 422  ← stops here
      3. (never reaches) connection check → 503

    Assigning a drone is required to bypass the "no assigned drone" 400 guard
    and reach the validation layer.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    body = {
        "name":              "GF-Upload-Test",
        "mission_type":      "ISR",
        "geofence":          _GEOFENCE,
        "drone_instance_id": gf_drone_instance["id"],
        "waypoints":         [_HOME_INSIDE, _WP_OUTSIDE],
    }
    create = await client.post("/api/flight/missions", json=body, headers=hdrs)
    assert create.status_code == 201, create.text
    mid = create.json()["id"]

    try:
        resp = await client.post(
            f"/api/flight/missions/{mid}/upload", headers=hdrs
        )
        assert resp.status_code == 422, (
            f"Expected 422 (geofence violation before MAVLink), got {resp.status_code}: {resp.text}"
        )
        detail = resp.json().get("detail", {})
        errors = detail.get("errors", []) if isinstance(detail, dict) else []
        gf_errors = [e for e in errors if "outside" in e.lower()]
        assert len(gf_errors) >= 1, f"422 response missing geofence error: {detail}"
    finally:
        await client.delete(f"/api/flight/missions/{mid}", headers=hdrs)
