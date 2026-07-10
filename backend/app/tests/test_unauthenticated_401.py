"""
Unauthenticated 401 — parametric sweep
=======================================
Every protected endpoint must reject requests with no Bearer token with 401.
This file covers the endpoints that were not already asserted in their
own dedicated test files.

Grouped by module; each entry is (method, path, body).
Tests are parameterised so failures name the exact endpoint.
"""
import pytest
from httpx import AsyncClient


# ── helpers ───────────────────────────────────────────────────────────────────

_POLYGON = {
    "type": "Polygon",
    "coordinates": [[[77.58, 12.97], [77.60, 12.97],
                     [77.60, 12.99], [77.58, 12.99], [77.58, 12.97]]],
}


async def _hit(client: AsyncClient, method: str, path: str, body=None) -> int:
    fn = getattr(client, method)
    kwargs = {"json": body} if body is not None else {}
    resp = await fn(path, **kwargs)
    return resp.status_code


# ══════════════════════════════════════════════════════════════════════
# drone_master — Drone Types
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("method,path,body", [
    ("get",    "/api/master/drone-types/stats",  None),
    ("get",    "/api/master/drone-types/999999", None),
    ("put",    "/api/master/drone-types/999999", {"name": "x", "manufacturer": "x",
                                                   "model": "x", "size_class": "small",
                                                   "mission_type": "ISR", "is_vtol": False,
                                                   "max_speed_ms": 1.0, "cruise_speed_ms": 0.5,
                                                   "max_altitude_m": 100.0, "endurance_h": 1.0,
                                                   "range_km": 10.0, "max_takeoff_weight_kg": 1.0,
                                                   "max_payload_weight_kg": 0.1,
                                                   "autopilot_type": "ArduPilot"}),
    ("delete", "/api/master/drone-types/999999", None),
])
async def test_drone_types_unauthenticated_401(
    client: AsyncClient, method, path, body
):
    assert await _hit(client, method, path, body) == 401


# ══════════════════════════════════════════════════════════════════════
# drone_master — Drone Instances
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("method,path,body", [
    ("get",    "/api/master/drones/999999",         None),
    ("put",    "/api/master/drones/999999",         {"call_sign": "X", "drone_type_id": 1,
                                                     "serial_number": "SN-X"}),
    ("patch",  "/api/master/drones/999999/status",  {"status": "offline"}),
    ("delete", "/api/master/drones/999999",         None),
    ("get",    "/api/master/drones/999999/type-spec", None),
])
async def test_drone_instances_unauthenticated_401(
    client: AsyncClient, method, path, body
):
    assert await _hit(client, method, path, body) == 401


# ══════════════════════════════════════════════════════════════════════
# drone_master — Naval Vessels
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("method,path,body", [
    ("get",    "/api/master/vessels/999999",                    None),
    ("put",    "/api/master/vessels/999999",                    {"name": "X", "vessel_id": "V-X",
                                                                  "vessel_type": "warship"}),
    ("post",   "/api/master/vessels/999999/position",           {"latitude": 12.0, "longitude": 77.0}),
    ("post",   "/api/master/vessels/999999/assign-drone/1",     None),
    ("post",   "/api/master/vessels/999999/unassign-drone/1",   None),
    ("delete", "/api/master/vessels/999999",                    None),
])
async def test_vessels_unauthenticated_401(
    client: AsyncClient, method, path, body
):
    assert await _hit(client, method, path, body) == 401


# ══════════════════════════════════════════════════════════════════════
# drone_master — Payload Types
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("method,path,body", [
    ("get",    "/api/master/payload-types",        None),
    ("get",    "/api/master/payload-types/999999", None),
    ("put",    "/api/master/payload-types/999999", {"name": "X", "manufacturer": "X",
                                                    "model": "X", "category": "sensor",
                                                    "weight_kg": 0.5, "voltage_v": 5.0,
                                                    "max_current_a": 1.0}),
    ("delete", "/api/master/payload-types/999999", None),
])
async def test_payload_types_unauthenticated_401(
    client: AsyncClient, method, path, body
):
    assert await _hit(client, method, path, body) == 401


# ══════════════════════════════════════════════════════════════════════
# drone_master — Config Templates
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("method,path,body", [
    ("get",    "/api/master/config-templates/999999",                  None),
    ("put",    "/api/master/config-templates/999999",                  {"name": "X",
                                                                         "drone_type_id": 1}),
    ("delete", "/api/master/config-templates/999999",                  None),
    ("post",   "/api/master/config-templates/999999/apply/1",          None),
])
async def test_config_templates_unauthenticated_401(
    client: AsyncClient, method, path, body
):
    assert await _hit(client, method, path, body) == 401


# ══════════════════════════════════════════════════════════════════════
# drone_flight — Missions
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("method,path,body", [
    ("post",  "/api/flight/missions",                   {"name": "X", "mission_type": "ISR",
                                                          "waypoints": []}),
    ("patch", "/api/flight/missions/999999/status",     {"status": "approved"}),
    ("get",   "/api/flight/missions/999999/summary",    None),
    ("get",   "/api/flight/missions/999999/simulate",   None),
    ("post",  "/api/flight/survey-grid",                {"polygon": _POLYGON,
                                                          "altitude_m": 50.0,
                                                          "overlap_pct": 70.0,
                                                          "speed_ms": 10.0}),
])
async def test_flight_missions_unauthenticated_401(
    client: AsyncClient, method, path, body
):
    assert await _hit(client, method, path, body) == 401


# ══════════════════════════════════════════════════════════════════════
# drone_inventory
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/inventory/drones/999999",              None),
    ("get", "/api/inventory/drones/999999/quick-ref",    None),
    ("get", "/api/inventory/compare?ids=1&ids=2",        None),
    ("get", "/api/inventory/payloads",                   None),
    ("get", "/api/inventory/threat-systems/999999",      None),
    ("put", "/api/inventory/threat-systems/999999",      {"name": "X", "category": "UAV",
                                                           "country": "Unknown"}),
    ("patch", "/api/inventory/threat-systems/999999/notes", {"notes": "test"}),
    ("delete", "/api/inventory/threat-systems/999999",   None),
])
async def test_inventory_unauthenticated_401(
    client: AsyncClient, method, path, body
):
    assert await _hit(client, method, path, body) == 401


# ══════════════════════════════════════════════════════════════════════
# drone_master — Config Templates — missing 403
# ══════════════════════════════════════════════════════════════════════

async def test_apply_config_template_viewer_403(
    client: AsyncClient, viewer_user, make_token
):
    """VIEWER cannot apply a config template → 403."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        "/api/master/config-templates/1/apply/1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# drone_master — Payload Types — missing 404
# ══════════════════════════════════════════════════════════════════════

async def test_update_payload_type_not_found_404(
    client: AsyncClient, admin_user, make_token
):
    """PUT on a non-existent payload type → 404."""
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.put(
        "/api/master/payload-types/999999",
        json={"name": "Ghost", "manufacturer": "X", "model": "X",
              "category": "sensor", "weight_kg": 0.1,
              "voltage_v": 5.0, "max_current_a": 0.5},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_delete_payload_type_not_found_404(
    client: AsyncClient, admin_user, make_token
):
    """DELETE on a non-existent payload type → 404."""
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.delete(
        "/api/master/payload-types/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# drone_master — Config Templates — missing 404
# ══════════════════════════════════════════════════════════════════════

async def test_delete_config_template_not_found_404(
    client: AsyncClient, admin_user, make_token
):
    """DELETE on a non-existent config template → 404."""
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.delete(
        "/api/master/config-templates/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# drone_flight — survey-grid 403
# ══════════════════════════════════════════════════════════════════════

async def test_survey_grid_viewer_403(
    client: AsyncClient, viewer_user, make_token
):
    """VIEWER cannot generate a survey grid → 403."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        "/api/flight/survey-grid",
        json={"polygon": _POLYGON, "altitude_m": 50.0,
              "overlap_pct": 70.0, "speed_ms": 10.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
