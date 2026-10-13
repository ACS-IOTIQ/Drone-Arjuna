"""
Drone Analyst read-only API tests
=================================
GET /api/analyst/status
GET /api/analyst/results
GET /api/analyst/models
GET /api/analyst/models/{model_id}
GET /api/analyst/missions/{mission_id}/stats
GET /api/analyst/missions/{mission_id}/series

(Job create/list/cancel and artifacts are covered in test_analyst_api.py and
test_analyst_artifacts.py.)

The conftest `_mock_ts_session` fixture swaps TimescaleDB for a session that
returns zero rows, so the default behaviour here is "no telemetry recorded".
The *_with_data tests install their own fake session to exercise the
aggregation / serialisation paths.

Covers:
  - status: counts jobs by state, reports V1 capabilities
  - results: V1 placeholder shape, echoes mission_id, limit bounds validated
  - models: registry list + detail, unknown id -> 404
  - stats: empty mission -> zero frame summary; mission with frames -> rounded stats
  - series: allowed param, bad param -> 400, bucket_seconds bounds, data serialisation
  - RBAC: VIEWER may read; unauthenticated -> 401
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

import app.modules.drone_analyst.service as analyst_service
from app.modules.drone_analyst.service import _MODEL_REGISTRY


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class _FakeResult:
    """Stand-in for a SQLAlchemy result: one scalar, one row, or many rows."""

    def __init__(self, scalar=None, one=None, rows=None):
        self._scalar, self._one, self._rows = scalar, one, rows or []

    def scalar_one(self):
        return self._scalar

    def mappings(self):
        m = AsyncMock()
        m.one = lambda: self._one
        m.all = lambda: self._rows
        return m


def _install_ts_session(monkeypatch, results: list):
    """Make TSSessionLocal() yield a session whose execute() returns `results` in order."""

    class _Session:
        async def __aenter__(self):
            sess = AsyncMock()
            sess.execute = AsyncMock(side_effect=list(results))
            return sess

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(analyst_service, "TSSessionLocal", lambda: _Session())


# ══════════════════════════════════════════════════════════════════════
# GET /status
# ══════════════════════════════════════════════════════════════════════

async def test_status_empty_db_200(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get("/api/analyst/status", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["module_version"] == "1.0.0"
    assert body["ai_inference_ready"] is False
    assert body["jobs"] == {"active": 0, "pending": 0, "complete": 0, "total": 0}
    assert body["registered_models"] == len(_MODEL_REGISTRY)
    assert "capabilities" in body


async def test_status_counts_queued_job(
    client: AsyncClient, mission_commander_user, make_token
):
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    created = await client.post(
        "/api/analyst/jobs",
        json={"job_type": "telemetry_report", "params": {}},
        headers=_auth(token),
    )
    assert created.status_code == 201, created.text

    resp = await client.get("/api/analyst/status", headers=_auth(token))
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    assert jobs["total"] == 1
    assert jobs["pending"] == 1
    assert jobs["active"] == 0


async def test_status_unauthenticated_401(client: AsyncClient):
    assert (await client.get("/api/analyst/status")).status_code == 401


# ══════════════════════════════════════════════════════════════════════
# GET /results
# ══════════════════════════════════════════════════════════════════════

async def test_results_v1_placeholder(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get("/api/analyst/results", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["results"] == []
    assert body["total"] == 0
    assert body["mission_id"] is None


async def test_results_echoes_mission_id_filter(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        "/api/analyst/results?mission_id=42&limit=10", headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["mission_id"] == 42


@pytest.mark.parametrize("limit", [0, 501, -1])
async def test_results_limit_out_of_range_422(
    client: AsyncClient, viewer_user, make_token, limit
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(f"/api/analyst/results?limit={limit}", headers=_auth(token))
    assert resp.status_code == 422


async def test_results_unauthenticated_401(client: AsyncClient):
    assert (await client.get("/api/analyst/results")).status_code == 401


# ══════════════════════════════════════════════════════════════════════
# GET /models, /models/{model_id}
# ══════════════════════════════════════════════════════════════════════

async def test_list_models_returns_registry(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get("/api/analyst/models", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == len(_MODEL_REGISTRY) == len(body["models"])
    ids = {m["id"] for m in body["models"]}
    assert {"yolov8n-coco", "yolov8m-military", "change-detect-v1"} <= ids
    for m in body["models"]:
        assert {"id", "name", "type", "framework", "status"} <= set(m)


@pytest.mark.parametrize("model_id", [m["id"] for m in _MODEL_REGISTRY])
async def test_get_model_detail_200(
    client: AsyncClient, viewer_user, make_token, model_id
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(f"/api/analyst/models/{model_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == model_id


async def test_get_unknown_model_404(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get("/api/analyst/models/does-not-exist", headers=_auth(token))
    assert resp.status_code == 404
    assert "does-not-exist" in resp.json()["detail"]


async def test_models_unauthenticated_401(client: AsyncClient):
    assert (await client.get("/api/analyst/models")).status_code == 401
    assert (await client.get("/api/analyst/models/yolov8n-coco")).status_code == 401


# ══════════════════════════════════════════════════════════════════════
# GET /missions/{mission_id}/stats
# ══════════════════════════════════════════════════════════════════════

async def test_mission_stats_without_telemetry_is_zeroed(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get("/api/analyst/missions/7/stats", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mission_id"] == 7
    assert body["frame_count"] == 0
    assert body["start_time"] is None and body["end_time"] is None
    assert body["duration_min"] == 0
    assert body["min_battery_pct"] == -1
    assert body["total_distance_km"] == 0


async def test_mission_stats_with_data_aggregates(
    client: AsyncClient, viewer_user, make_token, monkeypatch
):
    start = datetime(2026, 5, 25, 9, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 25, 9, 30, 0, tzinfo=timezone.utc)
    _install_ts_session(monkeypatch, [
        _FakeResult(scalar=120),
        _FakeResult(one={
            "frame_count": 120, "start_time": start, "end_time": end,
            "avg_altitude_m": 48.25, "max_altitude_m": 60.0,
            "avg_speed_ms": 9.5, "max_speed_ms": 12.0,
            "min_battery_pct": 61, "avg_cpu_pct": 14.5,
        }),
        _FakeResult(one={"total_distance_m": 2345.0}),
    ])
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get("/api/analyst/missions/3/stats", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mission_id"] == 3
    assert body["frame_count"] == 120
    assert body["duration_min"] == 30.0
    assert body["avg_altitude_m"] == 48.25
    assert body["max_speed_ms"] == 12.0
    assert body["min_battery_pct"] == 61
    assert body["total_distance_km"] == 2.35          # 2345 m, rounded to 2 dp
    assert body["start_time"].startswith("2026-05-25T09:00:00")


async def test_mission_stats_non_integer_id_422(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get("/api/analyst/missions/abc/stats", headers=_auth(token))
    assert resp.status_code == 422


async def test_mission_stats_unauthenticated_401(client: AsyncClient):
    assert (await client.get("/api/analyst/missions/1/stats")).status_code == 401


# ══════════════════════════════════════════════════════════════════════
# GET /missions/{mission_id}/series
# ══════════════════════════════════════════════════════════════════════

async def test_mission_series_defaults_empty(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get("/api/analyst/missions/7/series", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mission_id"] == 7
    assert body["param"] == "alt_agl"          # default parameter
    assert body["bucket_seconds"] == 5         # default bucket
    assert body["series"] == []


async def test_mission_series_with_data_serialises_points(
    client: AsyncClient, viewer_user, make_token, monkeypatch
):
    t0 = datetime(2026, 5, 25, 9, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 5, 25, 9, 0, 10, tzinfo=timezone.utc)
    _install_ts_session(monkeypatch, [
        _FakeResult(rows=[
            {"bucket": t0, "value": 31.456},
            {"bucket": t1, "value": None},     # a bucket with no samples
        ]),
    ])
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        "/api/analyst/missions/3/series?param=groundspeed_ms&bucket_seconds=10",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["param"] == "groundspeed_ms"
    assert body["bucket_seconds"] == 10
    assert body["series"][0]["value"] == 31.46          # rounded to 2 dp
    assert body["series"][0]["t"].startswith("2026-05-25T09:00:00")
    assert body["series"][1]["value"] is None


@pytest.mark.parametrize("param", [
    "alt_agl", "alt_msl", "groundspeed_ms", "airspeed_ms", "climb_rate_ms",
    "battery_remaining_pct", "battery_voltage_v", "heading", "roll_deg",
    "pitch_deg", "rssi", "cpu_load_pct",
])
async def test_mission_series_every_allowed_param_200(
    client: AsyncClient, viewer_user, make_token, param
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/analyst/missions/1/series?param={param}", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["param"] == param


async def test_mission_series_rejects_unknown_param_400(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        "/api/analyst/missions/1/series?param=nope", headers=_auth(token)
    )
    assert resp.status_code == 400
    assert "param must be one of" in resp.json()["detail"]


async def test_mission_series_param_is_never_interpolated_unchecked(
    client: AsyncClient, viewer_user, make_token
):
    """`param` is formatted into the SQL text, so the allow-list is the only guard."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        "/api/analyst/missions/1/series",
        params={"param": "alt_agl); DROP TABLE telemetry;--"},
        headers=_auth(token),
    )
    assert resp.status_code == 400


@pytest.mark.parametrize("bucket", [0, 301, -5])
async def test_mission_series_bucket_out_of_range_422(
    client: AsyncClient, viewer_user, make_token, bucket
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/analyst/missions/1/series?bucket_seconds={bucket}", headers=_auth(token)
    )
    assert resp.status_code == 422


async def test_mission_series_unauthenticated_401(client: AsyncClient):
    assert (await client.get("/api/analyst/missions/1/series")).status_code == 401
