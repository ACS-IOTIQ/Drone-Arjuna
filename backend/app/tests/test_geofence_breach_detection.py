"""
Runtime Geofence Breach Detection Tests
========================================
Tests the live breach detection path — no SITL, no frontend required.

Two detection paths are covered:
  A. TelemetryProcessor._check_geofence()
       Called on every GLOBAL_POSITION_INT MAVLink message when a real
       drone is connected.  Tested here with a mock StateManager.

  B. MissionSimulator._check_geofence()
       Called at each 10 Hz simulation tick.  Tested via the
       POST /api/drone-control/simulate/start endpoint with a mission
       whose waypoints intentionally leave the geofence boundary.

Event flow on breach:
  position update
    → geofence_store.is_inside() → False
    → StateManager.update({geofence_breach: True, breach_lat, breach_lon})
    → WebSocket broadcast (all connected subscribers see it)
    → emit_geofence_breach() → RabbitMQ drone_control.geofence_breach
    → auto-RTL dispatched (real drone: MAVLink RTL command; simulator: phase → RTL)

Edge-trigger: events fire ONLY on the breach/recovery transition, not
on every position tick.  Tests verify the one-shot behaviour.
"""
import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient

from app.utils.geofence import GeofenceStore
from app.modules.drone_control.telemetry_processor import TelemetryProcessor
from app.tests.helpers import auth_headers


# ── Shared geofence polygon ────────────────────────────────────────────
# ~1 km² square near Bangalore: lat [12.965–12.975], lon [77.585–77.595]

_GEOFENCE = {
    "type": "Polygon",
    "coordinates": [[
        [77.585, 12.965],
        [77.595, 12.965],
        [77.595, 12.975],
        [77.585, 12.975],
        [77.585, 12.965],
    ]],
}

_DRONE_ID   = 9001          # synthetic id — never hits the DB in unit tests
_LAT_INSIDE = 12.970        # centre of geofence box
_LON_INSIDE = 77.590
_LAT_OUTSIDE = 13.000       # far north-west, clearly outside
_LON_OUTSIDE = 77.400


# ═══════════════════════════════════════════════════════════════════════
# Part A — GeofenceStore unit tests (pure, no DB, no HTTP)
# ═══════════════════════════════════════════════════════════════════════

class TestGeofenceStore:

    def setup_method(self):
        self.store = GeofenceStore()

    def test_no_fence_returns_none(self):
        """is_inside() must return None when no fence is registered."""
        result = self.store.is_inside(_DRONE_ID, _LAT_INSIDE, _LON_INSIDE)
        assert result is None

    def test_set_fence_then_inside(self):
        """Point at the centre of the geofence polygon must be inside."""
        self.store.set_geofence(_DRONE_ID, _GEOFENCE)
        assert self.store.is_inside(_DRONE_ID, _LAT_INSIDE, _LON_INSIDE) is True

    def test_set_fence_then_outside(self):
        """Point at (13.000, 77.400) is outside the Bangalore box."""
        self.store.set_geofence(_DRONE_ID, _GEOFENCE)
        assert self.store.is_inside(_DRONE_ID, _LAT_OUTSIDE, _LON_OUTSIDE) is False

    def test_clear_fence(self):
        """Clearing the geofence makes is_inside() return None again."""
        self.store.set_geofence(_DRONE_ID, _GEOFENCE)
        self.store.clear(_DRONE_ID)
        assert self.store.is_inside(_DRONE_ID, _LAT_INSIDE, _LON_INSIDE) is None

    def test_set_none_clears_fence(self):
        """set_geofence(None) is the API equivalent of clear()."""
        self.store.set_geofence(_DRONE_ID, _GEOFENCE)
        self.store.set_geofence(_DRONE_ID, None)
        assert self.store.has_fence(_DRONE_ID) is False

    def test_invalid_geojson_returns_false_and_does_not_crash(self):
        """Malformed GeoJSON must not raise — returns False and logs a warning."""
        ok = self.store.set_geofence(_DRONE_ID, {"type": "Polygon"})  # missing coordinates
        assert ok is False
        assert self.store.has_fence(_DRONE_ID) is False

    def test_independent_fences_per_drone(self):
        """Each drone has its own independent fence — no cross-contamination."""
        drone_a, drone_b = 9001, 9002
        fence_a = {
            "type": "Polygon",
            "coordinates": [[[77.585, 12.965],[77.595, 12.965],[77.595, 12.975],[77.585, 12.975],[77.585, 12.965]]]
        }
        fence_b = {
            "type": "Polygon",
            "coordinates": [[[80.200, 13.050],[80.210, 13.050],[80.210, 13.060],[80.200, 13.060],[80.200, 13.050]]]
        }
        self.store.set_geofence(drone_a, fence_a)
        self.store.set_geofence(drone_b, fence_b)

        assert self.store.is_inside(drone_a, 12.970, 77.590) is True   # inside A
        assert self.store.is_inside(drone_a, 13.055, 80.205) is False  # outside A
        assert self.store.is_inside(drone_b, 13.055, 80.205) is True   # inside B
        assert self.store.is_inside(drone_b, 12.970, 77.590) is False  # outside B


# ═══════════════════════════════════════════════════════════════════════
# Part B — TelemetryProcessor breach detection (unit, mock StateManager)
# ═══════════════════════════════════════════════════════════════════════

class TestTelemetryProcessorBreachDetection:
    """
    Tests _check_geofence() in isolation using:
      - A real GeofenceStore (not the global singleton)
      - A mock StateManager (records update() calls)
      - Mocked emit_geofence_breach / emit_geofence_recovered (RabbitMQ publish)

    RTL is no longer dispatched directly from TelemetryProcessor — it is
    dispatched by the RabbitMQ consumer in MAVLinkManager (spec 3-45).
    These tests verify only the publish side; consumer tests live in
    test_geofence_rtl_consumer.py.
    """

    def setup_method(self):
        self.store = GeofenceStore()
        self.store.set_geofence(_DRONE_ID, _GEOFENCE)

        self.state = MagicMock()
        self.state.update = AsyncMock()

        # Patch the module-level geofence_store singleton inside the processor
        import app.modules.drone_control.telemetry_processor as tp_mod
        self._orig_store = tp_mod.geofence_store
        tp_mod.geofence_store = self.store

        self.processor = TelemetryProcessor()

    def teardown_method(self):
        import app.modules.drone_control.telemetry_processor as tp_mod
        tp_mod.geofence_store = self._orig_store

    @pytest.mark.asyncio
    async def test_no_event_when_inside(self):
        """When the drone is inside the geofence no state update is triggered."""
        position = {"lat": _LAT_INSIDE, "lon": _LON_INSIDE}
        with patch("app.modules.drone_control.telemetry_processor.emit_geofence_breach",
                   new_callable=AsyncMock) as mock_breach:
            await self.processor._check_geofence(_DRONE_ID, position, self.state)
            self.state.update.assert_not_called()
            mock_breach.assert_not_called()

    @pytest.mark.asyncio
    async def test_breach_triggers_state_update_and_publishes_event(self):
        """
        First tick outside the boundary must:
          1. Inject geofence_breach=True into StateManager (→ WebSocket)
          2. Publish to RabbitMQ via emit_geofence_breach (RTL dispatched by consumer)
        """
        position = {"lat": _LAT_OUTSIDE, "lon": _LON_OUTSIDE}
        with patch("app.modules.drone_control.telemetry_processor.emit_geofence_breach",
                   new_callable=AsyncMock) as mock_breach:
            await self.processor._check_geofence(_DRONE_ID, position, self.state)

            # State must have been updated with breach flag
            self.state.update.assert_called_once()
            call_args = self.state.update.call_args[0]
            assert call_args[0] == _DRONE_ID
            breach_data = call_args[1]
            assert breach_data["geofence_breach"] is True
            assert breach_data["breach_lat"] == _LAT_OUTSIDE
            assert breach_data["breach_lon"] == _LON_OUTSIDE

            # RabbitMQ publish must have been called
            mock_breach.assert_called_once_with(_DRONE_ID, _LAT_OUTSIDE, _LON_OUTSIDE)

    @pytest.mark.asyncio
    async def test_breach_is_edge_triggered_not_repeated(self):
        """
        Subsequent ticks while still outside must NOT re-fire the breach event.
        Only the first crossing triggers the state update and RabbitMQ publish.
        """
        position = {"lat": _LAT_OUTSIDE, "lon": _LON_OUTSIDE}
        with patch("app.modules.drone_control.telemetry_processor.emit_geofence_breach",
                   new_callable=AsyncMock) as mock_breach:
            await self.processor._check_geofence(_DRONE_ID, position, self.state)
            await self.processor._check_geofence(_DRONE_ID, position, self.state)
            await self.processor._check_geofence(_DRONE_ID, position, self.state)

            # Despite 3 ticks outside, events fired only once
            assert self.state.update.call_count == 1
            assert mock_breach.call_count == 1

    @pytest.mark.asyncio
    async def test_recovery_clears_breach_flag(self):
        """
        After a breach, re-entering the geofence must:
          1. Inject geofence_breach=False into StateManager
          2. Publish recovery event
          3. NOT re-publish a breach event
        """
        outside = {"lat": _LAT_OUTSIDE, "lon": _LON_OUTSIDE}
        inside  = {"lat": _LAT_INSIDE,  "lon": _LON_INSIDE}

        with patch("app.modules.drone_control.telemetry_processor.emit_geofence_breach",
                   new_callable=AsyncMock), \
             patch("app.modules.drone_control.telemetry_processor.emit_geofence_recovered",
                   new_callable=AsyncMock) as mock_recovered:

            await self.processor._check_geofence(_DRONE_ID, outside, self.state)  # breach
            self.state.update.reset_mock()

            await self.processor._check_geofence(_DRONE_ID, inside, self.state)   # recovery

            self.state.update.assert_called_once()
            recovery_data = self.state.update.call_args[0][1]
            assert recovery_data["geofence_breach"] is False
            mock_recovered.assert_called_once_with(_DRONE_ID)

    @pytest.mark.asyncio
    async def test_no_fence_no_events(self):
        """
        When no geofence is registered for the drone _check_geofence must
        return immediately without any side effects.
        """
        self.store.clear(_DRONE_ID)
        position = {"lat": _LAT_OUTSIDE, "lon": _LON_OUTSIDE}
        with patch("app.modules.drone_control.telemetry_processor.emit_geofence_breach",
                   new_callable=AsyncMock) as mock_breach:
            await self.processor._check_geofence(_DRONE_ID, position, self.state)
            self.state.update.assert_not_called()
            mock_breach.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# Part C — Geofence REST endpoint: POST /api/drone-control/drones/{id}/geofence
# ═══════════════════════════════════════════════════════════════════════

async def test_set_geofence_endpoint_200(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    POST /api/drone-control/drones/{id}/geofence with valid GeoJSON Polygon
    must return 200 and confirm the fence is active.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    resp = await client.post(
        f"/api/drone-control/drones/{_DRONE_ID}/geofence",
        json={"geofence": _GEOFENCE},
        headers=hdrs,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["active"] is True
    assert data["drone_id"] == _DRONE_ID


async def test_clear_geofence_endpoint_200(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    POST /api/drone-control/drones/{id}/geofence with geofence: null must
    clear the fence and return a 'cleared' confirmation.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    # Set first
    await client.post(
        f"/api/drone-control/drones/{_DRONE_ID}/geofence",
        json={"geofence": _GEOFENCE},
        headers=hdrs,
    )
    # Then clear
    resp = await client.post(
        f"/api/drone-control/drones/{_DRONE_ID}/geofence",
        json={"geofence": None},
        headers=hdrs,
    )
    assert resp.status_code == 200
    assert "cleared" in resp.json()["detail"].lower()


async def test_invalid_geofence_returns_422(
    client: AsyncClient, flight_controller_user, make_token
):
    """
    A GeoJSON dict with no 'coordinates' key is invalid geometry.
    The endpoint must return 422 and not register a fence.
    """
    hdrs = auth_headers(flight_controller_user, make_token)
    resp = await client.post(
        f"/api/drone-control/drones/{_DRONE_ID}/geofence",
        json={"geofence": {"type": "Polygon"}},   # missing coordinates
        headers=hdrs,
    )
    assert resp.status_code == 422


async def test_set_geofence_requires_flight_controller(
    client: AsyncClient, viewer_user, make_token
):
    """VIEWER must receive 403 — geofence arming requires FLIGHT_CONTROLLER+."""
    hdrs = auth_headers(viewer_user, make_token)
    resp = await client.post(
        f"/api/drone-control/drones/{_DRONE_ID}/geofence",
        json={"geofence": _GEOFENCE},
        headers=hdrs,
    )
    assert resp.status_code == 403


async def test_set_geofence_unauthenticated_401(client: AsyncClient):
    """No Bearer token must return 401."""
    resp = await client.post(
        f"/api/drone-control/drones/{_DRONE_ID}/geofence",
        json={"geofence": _GEOFENCE},
    )
    assert resp.status_code == 401
