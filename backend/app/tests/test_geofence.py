"""
Tests for:
  - app.utils.geofence.GeofenceStore  (pure unit, no DB/RabbitMQ)
  - TelemetryProcessor geofence breach detection

GeoJSON coordinate order: [longitude, latitude] — matches Shapely (x, y).
Fence used throughout: a 1-degree square lon=[0,1], lat=[0,1].
  Inside point : lat=0.5, lon=0.5  → Point(0.5, 0.5)
  Outside point: lat=2.0, lon=0.5  → Point(0.5, 2.0)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ── Constants ─────────────────────────────────────────────────────────────────

_DRONE_A = 10
_DRONE_B = 11

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

_INSIDE  = {"lat": 0.5, "lon": 0.5}
_OUTSIDE = {"lat": 2.0, "lon": 0.5}


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_store():
    """Clear the geofence singleton before and after each test."""
    from app.utils.geofence import geofence_store
    geofence_store.clear(_DRONE_A)
    geofence_store.clear(_DRONE_B)
    yield
    geofence_store.clear(_DRONE_A)
    geofence_store.clear(_DRONE_B)


@pytest.fixture
def processor():
    from app.modules.drone_control.telemetry_processor import TelemetryProcessor
    return TelemetryProcessor()


@pytest.fixture
def state():
    from app.modules.drone_control.state_manager import StateManager
    sm = StateManager()
    sm.init_drone(_DRONE_A, "ARJUNA-01")
    return sm


# ════════════════════════════════════════════════════════════════════════
# GeofenceStore — synchronous unit tests
# ════════════════════════════════════════════════════════════════════════

class TestGeofenceStore:

    # ── is_inside with no fence registered ───────────────────────────────

    def test_no_fence_returns_none(self):
        from app.utils.geofence import geofence_store
        assert geofence_store.is_inside(_DRONE_A, 0.5, 0.5) is None

    def test_has_fence_false_before_registration(self):
        from app.utils.geofence import geofence_store
        assert geofence_store.has_fence(_DRONE_A) is False

    # ── Basic inside/outside ──────────────────────────────────────────────

    def test_point_inside_returns_true(self):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        assert geofence_store.is_inside(_DRONE_A, lat=0.5, lon=0.5) is True

    def test_point_outside_returns_false(self):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        assert geofence_store.is_inside(_DRONE_A, lat=2.0, lon=0.5) is False

    def test_point_far_outside_returns_false(self):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        assert geofence_store.is_inside(_DRONE_A, lat=-90.0, lon=180.0) is False

    def test_boundary_point_returns_false(self):
        """
        Shapely .contains() excludes boundary — a point exactly on an edge
        is not considered inside.  Document this known behavior.
        """
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        # Exactly on the western edge: lon=0.0, lat=0.5
        assert geofence_store.is_inside(_DRONE_A, lat=0.5, lon=0.0) is False

    # ── MultiPolygon ─────────────────────────────────────────────────────

    def test_multipolygon_point_in_first_patch(self):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _MULTI)
        assert geofence_store.is_inside(_DRONE_A, lat=0.5, lon=0.5) is True

    def test_multipolygon_point_in_second_patch(self):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _MULTI)
        assert geofence_store.is_inside(_DRONE_A, lat=5.5, lon=5.5) is True

    def test_multipolygon_point_between_patches_returns_false(self):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _MULTI)
        assert geofence_store.is_inside(_DRONE_A, lat=3.0, lon=3.0) is False

    # ── Registration / lifecycle ─────────────────────────────────────────

    def test_valid_set_returns_true(self):
        from app.utils.geofence import geofence_store
        assert geofence_store.set_geofence(_DRONE_A, _SQUARE) is True

    def test_has_fence_true_after_registration(self):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        assert geofence_store.has_fence(_DRONE_A) is True

    def test_clear_removes_fence(self):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        geofence_store.clear(_DRONE_A)
        assert geofence_store.is_inside(_DRONE_A, lat=0.5, lon=0.5) is None
        assert geofence_store.has_fence(_DRONE_A) is False

    def test_set_none_clears_fence(self):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        result = geofence_store.set_geofence(_DRONE_A, None)
        assert result is True
        assert geofence_store.has_fence(_DRONE_A) is False
        assert geofence_store.is_inside(_DRONE_A, lat=0.5, lon=0.5) is None

    def test_replace_fence_uses_new_geometry(self):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)        # covers (0.5, 0.5)
        far_square = {
            "type": "Polygon",
            "coordinates": [[[10.0, 10.0], [11.0, 10.0], [11.0, 11.0],
                              [10.0, 11.0], [10.0, 10.0]]],
        }
        geofence_store.set_geofence(_DRONE_A, far_square)     # replaces
        assert geofence_store.is_inside(_DRONE_A, lat=0.5, lon=0.5) is False
        assert geofence_store.is_inside(_DRONE_A, lat=10.5, lon=10.5) is True

    # ── Error handling ────────────────────────────────────────────────────

    def test_invalid_geojson_type_returns_false(self):
        from app.utils.geofence import geofence_store
        result = geofence_store.set_geofence(_DRONE_A, {"type": "NotAGeom"})
        assert result is False
        assert geofence_store.has_fence(_DRONE_A) is False

    def test_invalid_geojson_missing_coords_returns_false(self):
        from app.utils.geofence import geofence_store
        result = geofence_store.set_geofence(_DRONE_A, {"type": "Polygon"})
        assert result is False
        assert geofence_store.has_fence(_DRONE_A) is False

    def test_invalid_geojson_does_not_overwrite_existing_fence(self):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        geofence_store.set_geofence(_DRONE_A, {"type": "BadGeom"})
        # Original fence still intact
        assert geofence_store.is_inside(_DRONE_A, lat=0.5, lon=0.5) is True

    # ── Multi-drone isolation ─────────────────────────────────────────────

    def test_multiple_drones_are_independent(self):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        # Drone B has no fence — must not inherit Drone A's fence
        assert geofence_store.is_inside(_DRONE_A, lat=0.5, lon=0.5) is True
        assert geofence_store.is_inside(_DRONE_B, lat=0.5, lon=0.5) is None

    def test_clearing_drone_a_does_not_affect_drone_b(self):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        geofence_store.set_geofence(_DRONE_B, _SQUARE)
        geofence_store.clear(_DRONE_A)
        assert geofence_store.has_fence(_DRONE_A) is False
        assert geofence_store.has_fence(_DRONE_B) is True


# ════════════════════════════════════════════════════════════════════════
# TelemetryProcessor — async geofence breach detection
# ════════════════════════════════════════════════════════════════════════

_BREACH_PATH  = "app.modules.drone_control.telemetry_processor.emit_geofence_breach"
_RECOVER_PATH = "app.modules.drone_control.telemetry_processor.emit_geofence_recovered"


class TestTelemetryProcessorGeofence:

    # ── No fence configured ───────────────────────────────────────────────

    async def test_no_fence_emits_no_events(self, processor, state):
        with patch(_BREACH_PATH,  new_callable=AsyncMock) as mb, \
             patch(_RECOVER_PATH, new_callable=AsyncMock) as mr:
            await processor._check_geofence(_DRONE_A, _INSIDE, state)
            mb.assert_not_called()
            mr.assert_not_called()

    # ── Initial breach ────────────────────────────────────────────────────

    async def test_first_breach_emits_breach_event(self, processor, state):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        with patch(_BREACH_PATH,  new_callable=AsyncMock) as mb, \
             patch(_RECOVER_PATH, new_callable=AsyncMock) as mr:
            await processor._check_geofence(_DRONE_A, _OUTSIDE, state)
            mb.assert_awaited_once_with(_DRONE_A, _OUTSIDE["lat"], _OUTSIDE["lon"])
            mr.assert_not_called()

    async def test_first_inside_emits_no_events(self, processor, state):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        with patch(_BREACH_PATH,  new_callable=AsyncMock) as mb, \
             patch(_RECOVER_PATH, new_callable=AsyncMock) as mr:
            await processor._check_geofence(_DRONE_A, _INSIDE, state)
            mb.assert_not_called()
            mr.assert_not_called()

    # ── Edge-triggered: no repeated events ───────────────────────────────

    async def test_continued_breach_does_not_repeat_event(self, processor, state):
        """Three consecutive outside readings → only one BREACH event (edge-triggered)."""
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        with patch(_BREACH_PATH, new_callable=AsyncMock) as mb:
            await processor._check_geofence(_DRONE_A, _OUTSIDE, state)
            await processor._check_geofence(_DRONE_A, _OUTSIDE, state)
            await processor._check_geofence(_DRONE_A, _OUTSIDE, state)
            assert mb.await_count == 1

    async def test_continued_inside_emits_no_events(self, processor, state):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        with patch(_BREACH_PATH,  new_callable=AsyncMock) as mb, \
             patch(_RECOVER_PATH, new_callable=AsyncMock) as mr:
            await processor._check_geofence(_DRONE_A, _INSIDE, state)
            await processor._check_geofence(_DRONE_A, {"lat": 0.3, "lon": 0.7}, state)
            mb.assert_not_called()
            mr.assert_not_called()

    # ── Recovery ──────────────────────────────────────────────────────────

    async def test_recovery_emits_recovered_event(self, processor, state):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        with patch(_BREACH_PATH,  new_callable=AsyncMock), \
             patch(_RECOVER_PATH, new_callable=AsyncMock) as mr:
            await processor._check_geofence(_DRONE_A, _OUTSIDE, state)  # breach
            await processor._check_geofence(_DRONE_A, _INSIDE,  state)  # recover
            mr.assert_awaited_once_with(_DRONE_A)

    async def test_continued_recovery_does_not_repeat_recovered_event(self, processor, state):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        with patch(_BREACH_PATH,  new_callable=AsyncMock), \
             patch(_RECOVER_PATH, new_callable=AsyncMock) as mr:
            await processor._check_geofence(_DRONE_A, _OUTSIDE, state)  # breach
            await processor._check_geofence(_DRONE_A, _INSIDE,  state)  # recover
            await processor._check_geofence(_DRONE_A, _INSIDE,  state)  # still inside
            assert mr.await_count == 1

    # ── Full breach / recover cycle ───────────────────────────────────────

    async def test_breach_recovery_breach_cycle(self, processor, state):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        with patch(_BREACH_PATH,  new_callable=AsyncMock) as mb, \
             patch(_RECOVER_PATH, new_callable=AsyncMock) as mr:
            await processor._check_geofence(_DRONE_A, _OUTSIDE, state)  # breach #1
            await processor._check_geofence(_DRONE_A, _INSIDE,  state)  # recover
            await processor._check_geofence(_DRONE_A, _OUTSIDE, state)  # breach #2
            assert mb.await_count == 2
            assert mr.await_count == 1

    # ── process() integration ─────────────────────────────────────────────

    async def test_process_position_outside_triggers_breach(self, processor, state):
        """GLOBAL_POSITION_INT with outside coordinates must emit a breach event."""
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)

        class _PosMsg:
            def get_type(self): return "GLOBAL_POSITION_INT"
            lat = int(2.0 * 1e7)   # 2.0° — outside fence (lat=[0,1])
            lon = int(0.5 * 1e7)
            alt = 100_000           # mm
            relative_alt = 50_000
            hdg = 9000              # centidegrees
            vx = vy = vz = 0

        with patch(_BREACH_PATH, new_callable=AsyncMock) as mb:
            await processor.process(_DRONE_A, _PosMsg(), state)
            mb.assert_awaited_once()

    async def test_process_position_inside_emits_nothing(self, processor, state):
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)

        class _PosMsg:
            def get_type(self): return "GLOBAL_POSITION_INT"
            lat = int(0.5 * 1e7)   # 0.5° — inside fence
            lon = int(0.5 * 1e7)
            alt = 100_000
            relative_alt = 50_000
            hdg = 0
            vx = vy = vz = 0

        with patch(_BREACH_PATH,  new_callable=AsyncMock) as mb, \
             patch(_RECOVER_PATH, new_callable=AsyncMock) as mr:
            await processor.process(_DRONE_A, _PosMsg(), state)
            mb.assert_not_called()
            mr.assert_not_called()

    async def test_process_attitude_message_skips_geofence(self, processor, state):
        """Non-position message types must not trigger geofence evaluation."""
        class _AttMsg:
            def get_type(self): return "ATTITUDE"
            roll = pitch = yaw = 0.0
            rollspeed = pitchspeed = yawspeed = 0.0

        with patch(_BREACH_PATH, new_callable=AsyncMock) as mb:
            await processor.process(_DRONE_A, _AttMsg(), state)
            mb.assert_not_called()

    async def test_process_position_no_fence_skips_check(self, processor, state):
        """When no fence is registered, process() must not emit any geofence events."""
        class _PosMsg:
            def get_type(self): return "GLOBAL_POSITION_INT"
            lat = int(99.0 * 1e7)  # far outside any plausible fence
            lon = int(99.0 * 1e7)
            alt = 0
            relative_alt = 0
            hdg = 0
            vx = vy = vz = 0

        with patch(_BREACH_PATH,  new_callable=AsyncMock) as mb, \
             patch(_RECOVER_PATH, new_callable=AsyncMock) as mr:
            await processor.process(_DRONE_A, _PosMsg(), state)
            mb.assert_not_called()
            mr.assert_not_called()


# ════════════════════════════════════════════════════════════════════════
# Auto-RTL — wired mavlink_manager dispatches RTL command on breach
# ════════════════════════════════════════════════════════════════════════

class TestAutoRTL:
    """
    When TelemetryProcessor is constructed with a mavlink_manager reference,
    a geofence breach must dispatch send_command(drone_id, "rtl", {}).
    Recovery and continued-breach ticks must NOT re-dispatch.
    """

    @pytest.fixture
    def mock_mav(self):
        m = MagicMock()
        m.send_command = AsyncMock()
        return m

    @pytest.fixture
    def proc_with_mav(self, mock_mav):
        from app.modules.drone_control.telemetry_processor import TelemetryProcessor
        return TelemetryProcessor(mock_mav)

    # ── RTL fires on breach ───────────────────────────────────────────────

    async def test_breach_dispatches_rtl(self, proc_with_mav, mock_mav, state):
        """First outside position → send_command('rtl') called exactly once."""
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        with patch(_BREACH_PATH, new_callable=AsyncMock):
            await proc_with_mav._check_geofence(_DRONE_A, _OUTSIDE, state)
        mock_mav.send_command.assert_awaited_once_with(_DRONE_A, "rtl", {})

    async def test_rtl_uses_correct_drone_id(self, proc_with_mav, mock_mav, state):
        """RTL must be sent for the breaching drone, not a different one."""
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        with patch(_BREACH_PATH, new_callable=AsyncMock):
            await proc_with_mav._check_geofence(_DRONE_A, _OUTSIDE, state)
        assert mock_mav.send_command.await_args[0][0] == _DRONE_A

    # ── Edge-triggered: no repeated RTL on the same breach ───────────────

    async def test_continued_breach_no_repeat_rtl(self, proc_with_mav, mock_mav, state):
        """Three consecutive outside readings → RTL dispatched only once."""
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        with patch(_BREACH_PATH, new_callable=AsyncMock):
            await proc_with_mav._check_geofence(_DRONE_A, _OUTSIDE, state)
            await proc_with_mav._check_geofence(_DRONE_A, _OUTSIDE, state)
            await proc_with_mav._check_geofence(_DRONE_A, _OUTSIDE, state)
        assert mock_mav.send_command.await_count == 1

    # ── No RTL on recovery or normal inside flight ────────────────────────

    async def test_recovery_does_not_dispatch_rtl(self, proc_with_mav, mock_mav, state):
        """Outside→inside transition emits RECOVERED but must not call RTL."""
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        with patch(_BREACH_PATH, new_callable=AsyncMock), \
             patch(_RECOVER_PATH, new_callable=AsyncMock):
            await proc_with_mav._check_geofence(_DRONE_A, _OUTSIDE, state)  # breach → RTL
            mock_mav.send_command.reset_mock()
            await proc_with_mav._check_geofence(_DRONE_A, _INSIDE,  state)  # recover
        mock_mav.send_command.assert_not_called()

    async def test_inside_position_no_rtl(self, proc_with_mav, mock_mav, state):
        """Drone inside the fence must never trigger RTL."""
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        with patch(_BREACH_PATH, new_callable=AsyncMock):
            await proc_with_mav._check_geofence(_DRONE_A, _INSIDE, state)
        mock_mav.send_command.assert_not_called()

    # ── RTL re-fires after a genuine second breach ────────────────────────

    async def test_second_breach_after_recovery_dispatches_rtl_again(
        self, proc_with_mav, mock_mav, state
    ):
        """
        breach #1 → RTL, recover, breach #2 → RTL again.
        Total send_command calls must be 2.
        """
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        with patch(_BREACH_PATH, new_callable=AsyncMock), \
             patch(_RECOVER_PATH, new_callable=AsyncMock):
            await proc_with_mav._check_geofence(_DRONE_A, _OUTSIDE, state)  # breach #1
            await proc_with_mav._check_geofence(_DRONE_A, _INSIDE,  state)  # recover
            await proc_with_mav._check_geofence(_DRONE_A, _OUTSIDE, state)  # breach #2
        assert mock_mav.send_command.await_count == 2

    # ── Backward-compat: mav=None raises no error ─────────────────────────

    async def test_no_mav_breach_still_emits_event(self, processor, state):
        """
        TelemetryProcessor(mav=None) — the default — must still emit the
        breach event and raise no AttributeError.
        """
        from app.utils.geofence import geofence_store
        geofence_store.set_geofence(_DRONE_A, _SQUARE)
        with patch(_BREACH_PATH, new_callable=AsyncMock) as mb:
            await processor._check_geofence(_DRONE_A, _OUTSIDE, state)
            mb.assert_awaited_once()

    async def test_no_fence_no_rtl(self, proc_with_mav, mock_mav, state):
        """When no fence is registered, no RTL must be dispatched."""
        with patch(_BREACH_PATH, new_callable=AsyncMock):
            await proc_with_mav._check_geofence(_DRONE_A, _OUTSIDE, state)
        mock_mav.send_command.assert_not_called()
