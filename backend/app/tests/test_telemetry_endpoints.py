"""
Telemetry Endpoints Tests — Priority 1
=======================================
GET /api/drone-control/telemetry/{drone_id}/gauges
GET /api/drone-control/telemetry/{drone_id}/history

Both endpoints require:
  - A connected drone (via MAVLinkManager state) OR return 404
  - VIEWER+ authentication OR return 401

Since tests run with no live MAVLink connection, the drone is never
in _connections, so _require_live_drone() always raises 404. This
exercises the auth layer, 404 path, and correct response shapes.

The TimescaleDB session is replaced by the conftest _mock_ts_session
fixture (autouse=True) which returns empty results for all TS queries.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from httpx import AsyncClient
from app.database import get_ts_db as _get_ts_db


# ── Shared drone fixture ──────────────────────────────────────────────────────

_DT_BODY = {
    "name":                  "Telemetry-Test DroneType",
    "manufacturer":          "DA Test Corp",
    "model":                 "TLM-1",
    "size_class":            "small",
    "mission_type":          "ISR",
    "is_vtol":               False,
    "max_speed_ms":          20.0,
    "cruise_speed_ms":       15.0,
    "max_altitude_m":        1500.0,
    "endurance_h":           1.0,
    "range_km":              25.0,
    "max_takeoff_weight_kg": 3.0,
    "max_payload_weight_kg": 0.5,
    "autopilot_type":        "ArduPilot",
}


import pytest_asyncio


@pytest_asyncio.fixture
async def drone_type(client: AsyncClient, admin_user, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.post("/api/master/drone-types", json=_DT_BODY, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data  = resp.json()
    yield data
    await client.delete(f"/api/master/drone-types/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def drone_instance(client: AsyncClient, admin_user, drone_type, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.post(
        "/api/master/drones",
        json={
            "call_sign":        "ALPHA-TLM",
            "serial_number":    "TLM-SN-001",
            "drone_type_id":    drone_type["id"],
            "notes":            "Telemetry test drone",
        },
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/master/drones/{data['id']}", headers=hdrs)


# ═════════════════════════════════════════════════════════════════════════════
# GET /api/drone-control/telemetry/{drone_id}/gauges
# ═════════════════════════════════════════════════════════════════════════════

class TestTelemetryGauges:

    async def test_gauges_requires_auth(self, client: AsyncClient, drone_instance):
        """No token → 401."""
        resp = await client.get(
            f"/api/drone-control/telemetry/{drone_instance['id']}/gauges"
        )
        assert resp.status_code == 401

    async def test_gauges_viewer_allowed(
        self, client: AsyncClient, drone_instance, viewer_user, make_token
    ):
        """VIEWER role is permitted (min role is VIEWER) — gets 404 not connected."""
        token = make_token(viewer_user.id, viewer_user.role)
        resp = await client.get(
            f"/api/drone-control/telemetry/{drone_instance['id']}/gauges",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Drone exists in DB but is not MAVLink-connected → 404 from _require_live_drone
        assert resp.status_code == 404

    async def test_gauges_404_when_drone_not_connected(
        self, client: AsyncClient, drone_instance, admin_user, make_token
    ):
        """Drone exists in DB but has no live MAVLink connection → 404."""
        token = make_token(admin_user.id, admin_user.role)
        resp = await client.get(
            f"/api/drone-control/telemetry/{drone_instance['id']}/gauges",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
        assert "not connected" in resp.json()["detail"].lower()

    async def test_gauges_404_unknown_drone_id(
        self, client: AsyncClient, admin_user, make_token
    ):
        """Drone ID does not exist in DB at all → 404."""
        token = make_token(admin_user.id, admin_user.role)
        resp = await client.get(
            "/api/drone-control/telemetry/999999/gauges",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    async def test_gauges_connected_drone_returns_gauge_shape(
        self, client: AsyncClient, drone_instance, admin_user, make_token
    ):
        """
        When drone IS connected (state in MAVLinkManager) and gauge data exists
        in TimescaleDB, the response contains the expected gauge keys.

        We mock _require_live_drone to pass, and mock the TS DB query to
        return a synthetic gauge row.
        """
        token = make_token(admin_user.id, admin_user.role)

        fake_row = {
            "recorded_at":    "2026-07-09T06:00:00+00:00",
            "battery_pct":    85,
            "altitude_m":     120.5,
            "ground_speed_ms": 14.2,
            "gps_satellites": 12,
            "rssi":           70,
            "cpu_load_pct":   22.5,
        }

        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = fake_row

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def _mock_ts_get_db():
            yield mock_session

        from app.main import app
        app.dependency_overrides[_get_ts_db] = _mock_ts_get_db
        try:
            with patch(
                "app.modules.drone_control.router._require_live_drone",
                new=AsyncMock(return_value={"drone_id": drone_instance["id"]}),
            ):
                resp = await client.get(
                    f"/api/drone-control/telemetry/{drone_instance['id']}/gauges",
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(_get_ts_db, None)

        assert resp.status_code == 200
        data = resp.json()
        assert "battery_remaining_pct" in data
        assert "alt_agl"               in data
        assert "groundspeed_ms"        in data
        assert "gps_satellites"        in data
        assert "rssi"                  in data
        assert "cpu_load_pct"          in data

    async def test_gauges_connected_drone_no_data_returns_404(
        self, client: AsyncClient, drone_instance, admin_user, make_token
    ):
        """
        Drone IS connected but no gauge rows exist yet in TimescaleDB → 404
        with 'No gauge data recorded' detail.
        """
        token = make_token(admin_user.id, admin_user.role)

        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def _mock_ts_get_db():
            yield mock_session

        from app.main import app
        app.dependency_overrides[_get_ts_db] = _mock_ts_get_db
        try:
            with patch(
                "app.modules.drone_control.router._require_live_drone",
                new=AsyncMock(return_value={"drone_id": drone_instance["id"]}),
            ):
                resp = await client.get(
                    f"/api/drone-control/telemetry/{drone_instance['id']}/gauges",
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(_get_ts_db, None)

        assert resp.status_code == 404
        assert "No gauge data" in resp.json()["detail"]


# ═════════════════════════════════════════════════════════════════════════════
# GET /api/drone-control/telemetry/{drone_id}/history
# ═════════════════════════════════════════════════════════════════════════════

class TestTelemetryHistory:
    """
    /history has NO _require_live_drone guard — it always returns a list
    (empty if no rows). All tests mock get_ts_db to avoid needing a live
    TimescaleDB connection.
    """

    async def test_history_requires_auth(self, client: AsyncClient, drone_instance):
        """No token → 401 (auth guard fires before DB access)."""
        resp = await client.get(
            f"/api/drone-control/telemetry/{drone_instance['id']}/history"
        )
        assert resp.status_code == 401

    def _make_mock_ts_override(self, rows=None):
        """Return a get_ts_db override that yields a mock session."""
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = rows if rows is not None else []
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def _override():
            yield mock_session

        return _override

    async def test_history_viewer_allowed(
        self, client: AsyncClient, drone_instance, viewer_user, make_token
    ):
        """VIEWER role is permitted — returns 200 with list (mocked TS DB)."""
        from app.main import app
        token = make_token(viewer_user.id, viewer_user.role)
        app.dependency_overrides[_get_ts_db] = self._make_mock_ts_override()
        try:
            resp = await client.get(
                f"/api/drone-control/telemetry/{drone_instance['id']}/history",
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            app.dependency_overrides.pop(_get_ts_db, None)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_history_returns_list_shape(
        self, client: AsyncClient, drone_instance, admin_user, make_token
    ):
        """Telemetry rows present → list of frame dicts with the expected keys."""
        from app.main import app
        token = make_token(admin_user.id, admin_user.role)
        fake_rows = [
            {
                "recorded_at": "2026-07-09T06:00:00+00:00",
                "lat": 12.9716, "lon": 77.5946,
                "alt_agl": 100.0, "yaw_deg": 45.0,
                "pitch_deg": 2.0, "roll_deg": -1.5,
            },
            {
                "recorded_at": "2026-07-09T06:00:05+00:00",
                "lat": 12.9720, "lon": 77.5950,
                "alt_agl": 102.0, "yaw_deg": 46.0,
                "pitch_deg": 2.1, "roll_deg": -1.4,
            },
        ]
        app.dependency_overrides[_get_ts_db] = self._make_mock_ts_override(fake_rows)
        try:
            resp = await client.get(
                f"/api/drone-control/telemetry/{drone_instance['id']}/history",
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            app.dependency_overrides.pop(_get_ts_db, None)
        assert resp.status_code == 200
        frames = resp.json()
        assert isinstance(frames, list)
        assert len(frames) == 2
        for frame in frames:
            assert "timestamp" in frame
            assert "lat"       in frame
            assert "lng"       in frame
            assert "alt"       in frame
            assert "yaw"       in frame
            assert "pitch"     in frame
            assert "roll"      in frame

    async def test_history_empty_when_no_telemetry(
        self, client: AsyncClient, drone_instance, admin_user, make_token
    ):
        """No rows in telemetry_history → 200 with empty list (absence is valid)."""
        from app.main import app
        token = make_token(admin_user.id, admin_user.role)
        app.dependency_overrides[_get_ts_db] = self._make_mock_ts_override()
        try:
            resp = await client.get(
                f"/api/drone-control/telemetry/{drone_instance['id']}/history",
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            app.dependency_overrides.pop(_get_ts_db, None)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_history_accepts_start_end_params(
        self, client: AsyncClient, drone_instance, admin_user, make_token
    ):
        """start/end query params accepted without 422 error."""
        from app.main import app
        token = make_token(admin_user.id, admin_user.role)
        app.dependency_overrides[_get_ts_db] = self._make_mock_ts_override()
        try:
            resp = await client.get(
                f"/api/drone-control/telemetry/{drone_instance['id']}/history"
                "?start=2026-07-09T00:00:00Z&end=2026-07-09T06:00:00Z",
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            app.dependency_overrides.pop(_get_ts_db, None)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_history_flight_controller_allowed(
        self, client: AsyncClient, drone_instance, flight_controller_user, make_token
    ):
        """FLIGHT_CONTROLLER role (above VIEWER) is permitted → 200 list."""
        from app.main import app
        token = make_token(flight_controller_user.id, flight_controller_user.role)
        app.dependency_overrides[_get_ts_db] = self._make_mock_ts_override()
        try:
            resp = await client.get(
                f"/api/drone-control/telemetry/{drone_instance['id']}/history",
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            app.dependency_overrides.pop(_get_ts_db, None)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
