"""
DataRecorder Unit Tests — Priority 3
=====================================
Tests the DataRecorder class in isolation — no database required.

Covers:
  - record() skips upsert when state is unchanged (change-detection)
  - record() writes when state changes on any _COMPARE_FIELDS value
  - record() treats a new drone_id as always-write (cold start)
  - record() updates _last after a write
  - _gauge_from_frame() maps fields correctly
  - _history_from_frame() maps fields correctly
  - Missing keys in state default to zero-values
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.modules.drone_control.data_recorder import DataRecorder


# ── Helpers ───────────────────────────────────────────────────────────────────

def _full_state(**overrides) -> dict:
    """Return a complete telemetry state dict with sensible defaults."""
    base = {
        "lat":                    12.9716,
        "lon":                    77.5946,
        "alt_msl":                500.0,
        "alt_agl":                100.0,
        "heading":                45.0,
        "roll_deg":               1.0,
        "pitch_deg":              2.0,
        "yaw_deg":                45.0,
        "vx":                     5.0,
        "vy":                     0.0,
        "vz":                     -0.5,
        "airspeed_ms":            14.0,
        "groundspeed_ms":         14.2,
        "climb_rate_ms":          0.1,
        "throttle_pct":           60,
        "battery_voltage_v":      16.5,
        "battery_current_a":      8.0,
        "battery_remaining_pct":  85,
        "gps_fix_type":           "3D_Fix",
        "gps_satellites":         12,
        "gps_hdop":               0.8,
        "flight_mode":            "AUTO",
        "is_armed":               True,
        "system_status":          4,
        "rssi":                   70,
        "cpu_load_pct":           22.5,
        "mission_id":             1,
        "current_waypoint":       3,
    }
    base.update(overrides)
    return base


def _make_recorder() -> DataRecorder:
    """Return a fresh DataRecorder instance."""
    return DataRecorder()


# ── change-detection: _last dict ──────────────────────────────────────────────

class TestChangeDetection:

    @pytest.mark.asyncio
    async def test_first_call_always_writes(self):
        """First record() for a drone_id must always write — no prior snapshot."""
        dr = _make_recorder()
        state = _full_state()
        written = False

        async def _fake_session_ctx():
            sess = AsyncMock()
            result = MagicMock()
            result.on_conflict_do_update = MagicMock(return_value=result)
            sess.execute = AsyncMock()
            sess.commit = AsyncMock()
            return sess

        # Patch TSSessionLocal so no real DB is needed
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch(
            "app.modules.drone_control.data_recorder.TSSessionLocal",
            return_value=mock_session,
        ):
            await dr.record(1, state)

        # _last must now contain an entry for drone 1
        assert 1 in dr._last

    @pytest.mark.asyncio
    async def test_identical_state_skips_write(self):
        """Calling record() twice with identical state must skip the second write."""
        dr = _make_recorder()
        state = _full_state()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch(
            "app.modules.drone_control.data_recorder.TSSessionLocal",
            return_value=mock_session,
        ):
            await dr.record(1, state)
            first_call_count = mock_session.execute.call_count

            await dr.record(1, state)   # identical — must not write
            second_call_count = mock_session.execute.call_count

        assert second_call_count == first_call_count, (
            "execute() was called again despite identical state — change-detection not working"
        )

    @pytest.mark.asyncio
    async def test_changed_state_writes_again(self):
        """A changed field in state must trigger a new write."""
        dr = _make_recorder()
        state = _full_state()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch(
            "app.modules.drone_control.data_recorder.TSSessionLocal",
            return_value=mock_session,
        ):
            await dr.record(1, state)
            count_after_first = mock_session.execute.call_count

            state["battery_remaining_pct"] = 80  # change one field
            await dr.record(1, state)
            count_after_second = mock_session.execute.call_count

        assert count_after_second > count_after_first, (
            "execute() was NOT called after state change — change-detection is over-filtering"
        )

    @pytest.mark.asyncio
    async def test_separate_drone_ids_tracked_independently(self):
        """Two drones with the same state are each written on first call."""
        dr = _make_recorder()
        state = _full_state()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch(
            "app.modules.drone_control.data_recorder.TSSessionLocal",
            return_value=mock_session,
        ):
            await dr.record(1, state)
            after_drone_1 = mock_session.execute.call_count
            await dr.record(2, state)   # same state, different drone — must write
            after_drone_2 = mock_session.execute.call_count

        assert after_drone_2 > after_drone_1
        assert 1 in dr._last
        assert 2 in dr._last

    @pytest.mark.asyncio
    async def test_last_updated_after_write(self):
        """_last[drone_id] must be updated to the new snapshot after writing."""
        dr = _make_recorder()
        state_a = _full_state(battery_remaining_pct=85)
        state_b = _full_state(battery_remaining_pct=70)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch(
            "app.modules.drone_control.data_recorder.TSSessionLocal",
            return_value=mock_session,
        ):
            await dr.record(1, state_a)
            snap_a = dr._last[1]

            await dr.record(1, state_b)
            snap_b = dr._last[1]

        assert snap_a != snap_b, "_last was not updated after second write"

    @pytest.mark.asyncio
    async def test_non_compare_field_change_does_not_trigger_write(self):
        """
        mission_id and current_waypoint are NOT in _COMPARE_FIELDS.
        Changing only those fields must not trigger a write.
        """
        dr = _make_recorder()
        state = _full_state(mission_id=1, current_waypoint=0)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch(
            "app.modules.drone_control.data_recorder.TSSessionLocal",
            return_value=mock_session,
        ):
            await dr.record(1, state)
            count_after_first = mock_session.execute.call_count

            state["mission_id"]       = 99
            state["current_waypoint"] = 5
            await dr.record(1, state)   # only non-compare fields changed
            count_after_second = mock_session.execute.call_count

        assert count_after_second == count_after_first, (
            "Non-compare-field change incorrectly triggered a write"
        )


# ── stop() ────────────────────────────────────────────────────────────────────

class TestStop:

    @pytest.mark.asyncio
    async def test_stop_clears_last(self):
        """stop() must clear the _last cache so next call is a cold start."""
        dr = _make_recorder()
        state = _full_state()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch(
            "app.modules.drone_control.data_recorder.TSSessionLocal",
            return_value=mock_session,
        ):
            await dr.record(1, state)

        assert 1 in dr._last
        await dr.stop()
        assert dr._last == {}


# ── _gauge_from_frame() ───────────────────────────────────────────────────────

class TestGaugeFromFrame:

    def _make_frame(self, **overrides) -> dict:
        now = datetime(2026, 7, 9, 6, 0, 0, tzinfo=timezone.utc)
        frame = {
            "recorded_at":           now,
            "drone_id":              1,
            "battery_remaining_pct": 85,
            "alt_agl":               100.0,
            "groundspeed_ms":        14.2,
            "gps_satellites":        12,
            "rssi":                  70,
            "cpu_load_pct":          22.5,
        }
        frame.update(overrides)
        return frame

    def test_gauge_maps_battery(self):
        frame = self._make_frame(battery_remaining_pct=75)
        gauge = DataRecorder._gauge_from_frame(frame)
        assert gauge["battery_pct"] == 75

    def test_gauge_maps_altitude(self):
        frame = self._make_frame(alt_agl=250.0)
        gauge = DataRecorder._gauge_from_frame(frame)
        assert gauge["altitude_m"] == 250.0

    def test_gauge_maps_groundspeed(self):
        frame = self._make_frame(groundspeed_ms=20.5)
        gauge = DataRecorder._gauge_from_frame(frame)
        assert gauge["ground_speed_ms"] == 20.5

    def test_gauge_maps_gps_satellites(self):
        frame = self._make_frame(gps_satellites=8)
        gauge = DataRecorder._gauge_from_frame(frame)
        assert gauge["gps_satellites"] == 8

    def test_gauge_maps_rssi(self):
        frame = self._make_frame(rssi=45)
        gauge = DataRecorder._gauge_from_frame(frame)
        assert gauge["rssi"] == 45

    def test_gauge_maps_cpu_load(self):
        frame = self._make_frame(cpu_load_pct=88.0)
        gauge = DataRecorder._gauge_from_frame(frame)
        assert gauge["cpu_load_pct"] == 88.0

    def test_gauge_preserves_drone_id_and_recorded_at(self):
        now = datetime(2026, 7, 9, tzinfo=timezone.utc)
        frame = self._make_frame(drone_id=42)
        frame["recorded_at"] = now
        gauge = DataRecorder._gauge_from_frame(frame)
        assert gauge["drone_id"]    == 42
        assert gauge["recorded_at"] == now

    def test_gauge_defaults_when_keys_missing(self):
        """Frame with no telemetry keys must produce zero defaults."""
        frame = {"recorded_at": datetime.now(timezone.utc), "drone_id": 1}
        gauge = DataRecorder._gauge_from_frame(frame)
        assert gauge["battery_pct"]    == -1
        assert gauge["altitude_m"]     == 0.0
        assert gauge["ground_speed_ms"] == 0.0
        assert gauge["gps_satellites"] == 0
        assert gauge["rssi"]           == 0
        assert gauge["cpu_load_pct"]   == 0.0


# ── _history_from_frame() ─────────────────────────────────────────────────────

class TestHistoryFromFrame:

    def _make_frame(self, **overrides) -> dict:
        now = datetime(2026, 7, 9, 6, 0, 0, tzinfo=timezone.utc)
        frame = {
            "recorded_at": now,
            "drone_id":    1,
            "lat":         12.9716,
            "lon":         77.5946,
            "alt_agl":     100.0,
            "yaw_deg":     45.0,
            "pitch_deg":   2.0,
            "roll_deg":    -1.5,
        }
        frame.update(overrides)
        return frame

    def test_history_maps_lat_lon(self):
        frame = self._make_frame(lat=13.0, lon=78.0)
        hist  = DataRecorder._history_from_frame(frame)
        assert hist["lat"] == 13.0
        assert hist["lon"] == 78.0

    def test_history_maps_alt_agl(self):
        frame = self._make_frame(alt_agl=300.0)
        hist  = DataRecorder._history_from_frame(frame)
        assert hist["alt_agl"] == 300.0

    def test_history_maps_attitude(self):
        frame = self._make_frame(yaw_deg=90.0, pitch_deg=5.0, roll_deg=-3.0)
        hist  = DataRecorder._history_from_frame(frame)
        assert hist["yaw_deg"]   == 90.0
        assert hist["pitch_deg"] == 5.0
        assert hist["roll_deg"]  == -3.0

    def test_history_preserves_drone_id_and_recorded_at(self):
        now   = datetime(2026, 7, 9, tzinfo=timezone.utc)
        frame = self._make_frame(drone_id=7)
        frame["recorded_at"] = now
        hist  = DataRecorder._history_from_frame(frame)
        assert hist["drone_id"]    == 7
        assert hist["recorded_at"] == now

    def test_history_defaults_when_keys_missing(self):
        """Frame with no position keys must produce 0.0 defaults."""
        frame = {"recorded_at": datetime.now(timezone.utc), "drone_id": 1}
        hist  = DataRecorder._history_from_frame(frame)
        assert hist["lat"]       == 0.0
        assert hist["lon"]       == 0.0
        assert hist["alt_agl"]   == 0.0
        assert hist["yaw_deg"]   == 0.0
        assert hist["pitch_deg"] == 0.0
        assert hist["roll_deg"]  == 0.0


# ── Compare fields completeness ────────────────────────────────────────────────

class TestCompareFields:

    def test_compare_fields_count(self):
        """_COMPARE_FIELDS must contain exactly the 26 documented sensor fields."""
        assert len(DataRecorder._COMPARE_FIELDS) == 26

    def test_compare_fields_excludes_recorded_at(self):
        assert "recorded_at" not in DataRecorder._COMPARE_FIELDS

    def test_compare_fields_excludes_mission_context(self):
        assert "mission_id"       not in DataRecorder._COMPARE_FIELDS
        assert "current_waypoint" not in DataRecorder._COMPARE_FIELDS

    def test_compare_fields_includes_battery(self):
        assert "battery_remaining_pct" in DataRecorder._COMPARE_FIELDS

    def test_compare_fields_includes_gps(self):
        assert "gps_satellites" in DataRecorder._COMPARE_FIELDS
        assert "gps_fix_type"   in DataRecorder._COMPARE_FIELDS
        assert "gps_hdop"       in DataRecorder._COMPARE_FIELDS

    def test_compare_fields_includes_position(self):
        for field in ("lat", "lon", "alt_msl", "alt_agl", "heading"):
            assert field in DataRecorder._COMPARE_FIELDS, f"Missing: {field}"
