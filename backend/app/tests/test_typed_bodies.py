"""M-02: endpoints that took raw dict bodies now validate type, range and unknown fields."""
import pytest
from httpx import AsyncClient

from app.schemas.ops import SurveyGridRequest
from app.tests.helpers import auth_headers

POLY = [[12.97, 77.58], [12.97, 77.60], [12.99, 77.60], [12.99, 77.58]]


# ── survey grid ──────────────────────────────────────────────────────

async def test_survey_grid_valid_request_ok(client: AsyncClient, flight_controller_user, make_token):
    resp = await client.post("/api/flight/survey-grid",
                             json={"polygon": POLY, "altitude_m": 80, "spacing_m": 50},
                             headers=auth_headers(flight_controller_user, make_token))
    assert resp.status_code == 200
    assert resp.json()["count"] > 0


@pytest.mark.parametrize("patch", [
    {"altitude_m": -5},
    {"altitude_m": 99999},
    {"spacing_m": 0},
    {"speed_ms": 0},
    {"polygon": POLY[:2]},                                  # < 3 points
    {"polygon": [[95, 10], [10, 10], [10, 20]]},            # lat out of range
    {"polygon": [["a", "b"], [1, 2], [3, 4]]},              # not numbers
    {"unexpected": "field"},                                # unknown key
])
async def test_survey_grid_rejects_bad_input(client, flight_controller_user, make_token, patch):
    body = {"polygon": POLY, "altitude_m": 80, "spacing_m": 50, **patch}
    resp = await client.post("/api/flight/survey-grid", json=body,
                             headers=auth_headers(flight_controller_user, make_token))
    assert resp.status_code == 422


def test_survey_grid_area_cap_blocks_resource_exhaustion():
    huge = [[0, 0], [0, 10], [10, 10], [10, 0]]
    with pytest.raises(ValueError, match="too large"):
        SurveyGridRequest(polygon=huge, altitude_m=50, spacing_m=1)


# ── drone status / payload ───────────────────────────────────────────

@pytest.mark.parametrize("body", [
    {"status": "exploded"},
    {"status": ""},
    {},
    {"status": "online", "role": "admin"},
])
async def test_drone_status_rejects_invalid_body(client, flight_controller_user, make_token, body):
    resp = await client.patch("/api/master/drones/1/status", json=body,
                              headers=auth_headers(flight_controller_user, make_token))
    assert resp.status_code == 422


@pytest.mark.parametrize("body", [{"payload_type_id": "abc"}, {"payload_type_id": 0},
                                  {"payload_type_id": 1, "x": 1}])
async def test_payload_assign_rejects_invalid_body(client, flight_controller_user, make_token, body):
    resp = await client.post("/api/master/drones/1/payload", json=body,
                             headers=auth_headers(flight_controller_user, make_token))
    assert resp.status_code == 422


# ── analyst jobs ─────────────────────────────────────────────────────

@pytest.mark.parametrize("body", [
    {"job_type": "telemetry_report", "mission_id": "x"},
    {"job_type": "telemetry_report", "drone_id": -1},
    {"job_type": "telemetry_report", "params": "not-a-dict"},
    {"job_type": "telemetry_report", "params": {"blob": "A" * 30000}},
    {"job_type": "telemetry_report", "submitted_by": 1},     # cannot spoof server-set fields
])
async def test_analyst_job_rejects_invalid_body(client, mission_commander_user, make_token, body):
    resp = await client.post("/api/analyst/jobs", json=body,
                             headers=auth_headers(mission_commander_user, make_token))
    assert resp.status_code == 422
