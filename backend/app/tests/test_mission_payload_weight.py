"""
Mission payload weight validation tests
========================================
Verifies that MissionValidator rejects or warns when a mission's
payload_weight_kg exceeds (or approaches) the assigned drone type's
max_payload_weight_kg.

Covered cases:
  - No payload declared        → valid, no payload error/warning
  - Payload well under limit   → valid, no payload error/warning
  - Payload at exact limit     → valid, no error (boundary)
  - Payload within 10% margin  → valid but adds a warning
  - Payload exceeds limit      → invalid, adds an error
  - Negative payload_weight_kg → 422 rejected by schema validator
  - No drone assigned          → payload check skipped entirely (valid)
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


# ── shared data ───────────────────────────────────────────────────────────────

_MAX_KG = 5.0   # max_payload_weight_kg used throughout

_DT_BODY = {
    "name":                  "PW-DroneType-Alpha",
    "manufacturer":          "ACS Systems",
    "model":                 "Alpha-PW",
    "size_class":            "medium",
    "mission_type":          "ISR",
    "is_vtol":               True,
    "max_speed_ms":          30.0,
    "cruise_speed_ms":       20.0,
    "max_altitude_m":        3000.0,
    "endurance_h":           4.0,
    "range_km":              80.0,
    "max_takeoff_weight_kg": 20.0,
    "max_payload_weight_kg": _MAX_KG,
    "autopilot_type":        "ArduPilot",
}

_HOME_WP = {
    "sequence":    1,
    "latitude":    12.9716,
    "longitude":   77.5946,
    "altitude_m":  0.0,
    "altitude_ref": "AGL",
    "action":      "none",
    "is_home":     True,
}
_TARGET_WP = {
    "sequence":    2,
    "latitude":    12.9800,
    "longitude":   77.6000,
    "altitude_m":  100.0,
    "altitude_ref": "AGL",
    "action":      "none",
}


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def drone_type(client: AsyncClient, admin_user, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.post("/api/master/drone-types", json=_DT_BODY, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/master/drone-types/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def drone_instance(client: AsyncClient, admin_user, drone_type, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    body  = {
        "call_sign":    "PW-ALPHA-01",
        "serial_number": "PW-SN-001",
        "drone_type_id": drone_type["id"],
    }
    resp = await client.post("/api/master/drones", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    yield resp.json()


async def _create_mission(
    client: AsyncClient,
    hdrs: dict,
    payload_kg: float | None = None,
    drone_instance_id: int | None = None,
) -> dict:
    """Helper: create a mission and return the parsed JSON body."""
    body = {
        "name":         "PW-Test-Mission",
        "mission_type": "ISR",
        "waypoints":    [_HOME_WP, _TARGET_WP],
    }
    if payload_kg is not None:
        body["payload_weight_kg"] = payload_kg
    if drone_instance_id is not None:
        body["drone_instance_id"] = drone_instance_id

    resp = await client.post("/api/flight/missions", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _validate(client: AsyncClient, mid: int, hdrs: dict) -> dict:
    resp = await client.post(f"/api/flight/missions/{mid}/validate", headers=hdrs)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _cleanup(client: AsyncClient, mid: int, hdrs: dict):
    await client.delete(f"/api/flight/missions/{mid}", headers=hdrs)


# ══════════════════════════════════════════════════════════════════════
# Schema validation (before the mission even hits the DB)
# ══════════════════════════════════════════════════════════════════════

async def test_negative_payload_weight_422(
    client: AsyncClient, flight_controller_user, make_token
):
    """Negative payload_weight_kg must be rejected by the Pydantic schema."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp  = await client.post(
        "/api/flight/missions",
        json={
            "name":             "Bad-Mission",
            "mission_type":     "ISR",
            "payload_weight_kg": -1.0,
            "waypoints":        [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# Validator — payload stored on mission and returned in GET
# ══════════════════════════════════════════════════════════════════════

async def test_payload_weight_persisted_and_returned(
    client: AsyncClient, flight_controller_user, make_token
):
    """payload_weight_kg round-trips through POST → GET."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    m = await _create_mission(client, hdrs, payload_kg=2.5)
    try:
        get = await client.get(f"/api/flight/missions/{m['id']}", headers=hdrs)
        assert get.status_code == 200
        assert get.json()["payload_weight_kg"] == 2.5
    finally:
        await _cleanup(client, m["id"], hdrs)


async def test_no_payload_declared_no_error(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """Mission with no payload_weight_kg → validate passes with no payload-related error."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    m = await _create_mission(
        client, hdrs, payload_kg=None, drone_instance_id=drone_instance["id"]
    )
    try:
        result = await _validate(client, m["id"], hdrs)
        payload_errors = [e for e in result["errors"] if "payload" in e.lower()]
        payload_warnings = [w for w in result["warnings"] if "payload" in w.lower()]
        assert payload_errors == []
        assert payload_warnings == []
    finally:
        await _cleanup(client, m["id"], hdrs)


# ══════════════════════════════════════════════════════════════════════
# Validator — below / at / near / over limit
# ══════════════════════════════════════════════════════════════════════

async def test_payload_under_limit_valid(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """Payload well under max (2 kg vs 5 kg limit) → no payload error or warning."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    m = await _create_mission(
        client, hdrs, payload_kg=2.0, drone_instance_id=drone_instance["id"]
    )
    try:
        result = await _validate(client, m["id"], hdrs)
        assert result["valid"] is True
        assert not any("payload" in e.lower() for e in result["errors"])
        assert not any("payload" in w.lower() for w in result["warnings"])
    finally:
        await _cleanup(client, m["id"], hdrs)


async def test_payload_at_exact_limit_valid(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """Payload exactly at max_payload_weight_kg → valid, no error."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    m = await _create_mission(
        client, hdrs, payload_kg=_MAX_KG, drone_instance_id=drone_instance["id"]
    )
    try:
        result = await _validate(client, m["id"], hdrs)
        assert not any("payload" in e.lower() for e in result["errors"])
    finally:
        await _cleanup(client, m["id"], hdrs)


async def test_payload_within_10pct_margin_warns(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """Payload within 10% of limit (4.6 kg vs 5.0 kg) → valid but adds a warning."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    near_limit = _MAX_KG * 0.92   # 4.6 kg — inside the 90-100% band
    m = await _create_mission(
        client, hdrs, payload_kg=near_limit, drone_instance_id=drone_instance["id"]
    )
    try:
        result = await _validate(client, m["id"], hdrs)
        assert result["valid"] is True
        assert not any("payload" in e.lower() for e in result["errors"])
        assert any("payload" in w.lower() for w in result["warnings"])
    finally:
        await _cleanup(client, m["id"], hdrs)


async def test_payload_exceeds_limit_invalid(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """Payload over max → validate returns valid=False with a payload error."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    over_limit = _MAX_KG + 1.0   # 6.0 kg
    m = await _create_mission(
        client, hdrs, payload_kg=over_limit, drone_instance_id=drone_instance["id"]
    )
    try:
        result = await _validate(client, m["id"], hdrs)
        assert result["valid"] is False
        assert any("payload" in e.lower() for e in result["errors"])
    finally:
        await _cleanup(client, m["id"], hdrs)


async def test_payload_error_message_contains_weights(
    client: AsyncClient, flight_controller_user, drone_instance, make_token
):
    """Error message must include both the declared weight and the drone's limit."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    over_limit = 7.5
    m = await _create_mission(
        client, hdrs, payload_kg=over_limit, drone_instance_id=drone_instance["id"]
    )
    try:
        result = await _validate(client, m["id"], hdrs)
        error_text = " ".join(result["errors"])
        assert str(over_limit) in error_text
        assert str(_MAX_KG) in error_text
    finally:
        await _cleanup(client, m["id"], hdrs)


# ══════════════════════════════════════════════════════════════════════
# Validator — no drone assigned (check skipped)
# ══════════════════════════════════════════════════════════════════════

async def test_payload_check_skipped_without_drone(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    When no drone is assigned the payload check cannot run (no max to compare
    against). The mission is still valid from a payload perspective.
    """
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    # Large payload, but no drone assigned → no drone type to check against
    m = await _create_mission(
        client, hdrs, payload_kg=999.0, drone_instance_id=None
    )
    try:
        result = await _validate(client, m["id"], hdrs)
        assert not any("payload" in e.lower() for e in result["errors"])
    finally:
        await _cleanup(client, m["id"], hdrs)
