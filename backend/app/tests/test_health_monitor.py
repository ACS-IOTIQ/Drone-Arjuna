"""
HealthMonitor Unit Tests — Priority 3
=======================================
Tests the HealthMonitor.evaluate() method in isolation — no database,
no MAVLink connection required.

Covers:
  - Battery RTL trigger: fires send_command + emit_health_alert when
    battery ≤ BATTERY_RTL_PCT and drone is armed and not already in RTL/LAND
  - Battery RTL: does NOT fire when already in RTL or LAND mode
  - Battery RTL: does NOT fire when drone is disarmed
  - Battery RTL: does NOT re-fire if alert was already sent (_has_fired)
  - Battery RTL: clears fired flag once battery recovers above threshold + 5
  - Battery warning: fires emit_health_alert (no RTL command) below BATTERY_WARN_PCT
  - Battery warning: does NOT re-fire if alert already sent
  - Battery warning: clears when battery recovers
  - Link warning: fires when RSSI < LINK_WARN_RSSI and rssi > 0
  - Link warning: does NOT fire when rssi == 0 (disconnected / unknown)
  - Link warning: clears when RSSI recovers
  - GPS warning: fires when satellites < GPS_WARN_SATS
  - GPS warning: clears when satellites recover
  - _has_fired / _mark_fired / _clear_fired: internal state management
  - Multiple drones tracked independently
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from app.modules.drone_control.health_monitor import (
    HealthMonitor,
    BATTERY_RTL_PCT,
    BATTERY_WARN_PCT,
    LINK_WARN_RSSI,
    GPS_WARN_SATS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_monitor() -> tuple[HealthMonitor, MagicMock]:
    """Return (HealthMonitor, mock_mavlink_manager)."""
    mav = MagicMock()
    mav.send_command = AsyncMock()
    return HealthMonitor(mav), mav


def _state(
    *,
    battery: int = 100,
    rssi: int = 255,
    sats: int = 12,
    cpu: float = 0.0,
    mode: str = "AUTO",
    armed: bool = True,
) -> dict:
    return {
        "battery_remaining_pct": battery,
        "rssi":                  rssi,
        "gps_satellites":        sats,
        "cpu_load_pct":          cpu,
        "flight_mode":           mode,
        "is_armed":              armed,
    }


# ── _has_fired / _mark_fired / _clear_fired ───────────────────────────────────

class TestFiredTracking:

    def test_has_fired_false_initially(self):
        mon, _ = _make_monitor()
        assert not mon._has_fired(1, "battery_rtl")

    def test_mark_fired_sets_flag(self):
        mon, _ = _make_monitor()
        mon._mark_fired(1, "battery_rtl")
        assert mon._has_fired(1, "battery_rtl")

    def test_clear_fired_removes_flag(self):
        mon, _ = _make_monitor()
        mon._mark_fired(1, "battery_rtl")
        mon._clear_fired(1, "battery_rtl")
        assert not mon._has_fired(1, "battery_rtl")

    def test_clear_fired_unknown_drone_is_safe(self):
        """Clearing a flag for a drone that never fired must not raise."""
        mon, _ = _make_monitor()
        mon._clear_fired(999, "battery_rtl")   # must not raise

    def test_flags_independent_per_drone(self):
        mon, _ = _make_monitor()
        mon._mark_fired(1, "battery_rtl")
        assert mon._has_fired(1, "battery_rtl")
        assert not mon._has_fired(2, "battery_rtl")

    def test_flags_independent_per_alert_type(self):
        mon, _ = _make_monitor()
        mon._mark_fired(1, "battery_rtl")
        assert not mon._has_fired(1, "battery_warn")


# ── Battery RTL trigger ───────────────────────────────────────────────────────

class TestBatteryRTL:

    @pytest.mark.asyncio
    async def test_rtl_fires_when_low_armed_in_auto(self):
        """Battery at RTL threshold, armed, not in RTL/LAND → RTL command + alert."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            await mon.evaluate(1, _state(battery=BATTERY_RTL_PCT, mode="AUTO", armed=True))

        mav.send_command.assert_awaited_once_with(1, "rtl", {})
        mock_alert.assert_awaited_once_with(1, "battery_rtl", BATTERY_RTL_PCT)

    @pytest.mark.asyncio
    async def test_rtl_fires_below_threshold(self):
        """Battery one below threshold must also trigger RTL."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            await mon.evaluate(1, _state(battery=BATTERY_RTL_PCT - 1, mode="LOITER", armed=True))

        mav.send_command.assert_awaited_once()
        mock_alert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rtl_does_not_fire_when_already_in_rtl(self):
        """Already in RTL mode → must not send redundant RTL command."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            await mon.evaluate(1, _state(battery=BATTERY_RTL_PCT, mode="RTL", armed=True))

        mav.send_command.assert_not_awaited()
        mock_alert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rtl_does_not_fire_when_landing(self):
        """Already in LAND mode → must not send RTL command."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            await mon.evaluate(1, _state(battery=BATTERY_RTL_PCT, mode="LAND", armed=True))

        mav.send_command.assert_not_awaited()
        mock_alert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rtl_does_not_fire_when_disarmed(self):
        """Disarmed drone with low battery → no RTL command (on ground already)."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            await mon.evaluate(1, _state(battery=BATTERY_RTL_PCT, mode="AUTO", armed=False))

        mav.send_command.assert_not_awaited()
        mock_alert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rtl_fires_only_once(self):
        """RTL alert must not repeat on subsequent evaluate() calls with same low battery."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            st = _state(battery=BATTERY_RTL_PCT, mode="AUTO", armed=True)
            await mon.evaluate(1, st)
            await mon.evaluate(1, st)   # second call — should not re-fire
            await mon.evaluate(1, st)   # third call

        assert mav.send_command.await_count == 1
        assert mock_alert.await_count == 1

    @pytest.mark.asyncio
    async def test_rtl_clears_after_recovery(self):
        """
        Once battery rises above BATTERY_RTL_PCT + 5, the flag clears.
        A subsequent low-battery event must fire again.
        """
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            # First low-battery event
            await mon.evaluate(1, _state(battery=BATTERY_RTL_PCT, mode="AUTO", armed=True))
            assert mav.send_command.await_count == 1

            # Battery recovers
            await mon.evaluate(1, _state(battery=BATTERY_RTL_PCT + 6, mode="AUTO", armed=True))
            assert not mon._has_fired(1, "battery_rtl"), "Flag not cleared after recovery"

            # Low again
            await mon.evaluate(1, _state(battery=BATTERY_RTL_PCT, mode="AUTO", armed=True))
            assert mav.send_command.await_count == 2

    @pytest.mark.asyncio
    async def test_rtl_skipped_when_battery_unknown(self):
        """battery_remaining_pct == -1 (unknown) must NOT trigger RTL."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            await mon.evaluate(1, _state(battery=-1, mode="AUTO", armed=True))

        mav.send_command.assert_not_awaited()
        mock_alert.assert_not_awaited()


# ── Battery warning ───────────────────────────────────────────────────────────

class TestBatteryWarning:

    @pytest.mark.asyncio
    async def test_warn_fires_below_warn_pct(self):
        """Battery at warn threshold → emit warning alert, no RTL command."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            await mon.evaluate(1, _state(battery=BATTERY_WARN_PCT, mode="AUTO", armed=True))

        # Warning alert must be emitted
        warning_calls = [c for c in mock_alert.call_args_list if c.args[1] == "battery_warn"]
        assert len(warning_calls) >= 1, "battery_warn alert was not emitted"

    @pytest.mark.asyncio
    async def test_warn_fires_only_once(self):
        """Battery warning must not repeat on subsequent calls."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            st = _state(battery=BATTERY_WARN_PCT, mode="AUTO", armed=True)
            await mon.evaluate(1, st)
            await mon.evaluate(1, st)

        warn_calls = [c for c in mock_alert.call_args_list if c.args[1] == "battery_warn"]
        assert len(warn_calls) == 1

    @pytest.mark.asyncio
    async def test_warn_clears_after_recovery(self):
        """Battery warning flag clears when battery > BATTERY_WARN_PCT + 5."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ):
            await mon.evaluate(1, _state(battery=BATTERY_WARN_PCT, mode="AUTO", armed=True))
            mon._mark_fired(1, "battery_warn")   # ensure flag is set

            await mon.evaluate(1, _state(battery=BATTERY_WARN_PCT + 6, mode="AUTO", armed=True))
            assert not mon._has_fired(1, "battery_warn"), "warn flag not cleared after recovery"

    @pytest.mark.asyncio
    async def test_warn_does_not_fire_above_threshold(self):
        """Battery comfortably above warn threshold → no warning."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            await mon.evaluate(1, _state(battery=80, mode="AUTO", armed=True))

        warn_calls = [c for c in mock_alert.call_args_list if c.args[1] == "battery_warn"]
        assert len(warn_calls) == 0


# ── Link quality warning ──────────────────────────────────────────────────────

class TestLinkWarning:

    @pytest.mark.asyncio
    async def test_link_warn_fires_on_weak_rssi(self):
        """RSSI below threshold and > 0 → link warning alert."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            await mon.evaluate(1, _state(rssi=LINK_WARN_RSSI - 1))

        warn_calls = [c for c in mock_alert.call_args_list if c.args[1] == "link_warn"]
        assert len(warn_calls) == 1
        assert mock_alert.call_args_list[0].args[2] == LINK_WARN_RSSI - 1

    @pytest.mark.asyncio
    async def test_link_warn_does_not_fire_on_rssi_zero(self):
        """RSSI == 0 means no telemetry link data — must not trigger warning."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            await mon.evaluate(1, _state(rssi=0))

        warn_calls = [c for c in mock_alert.call_args_list if c.args[1] == "link_warn"]
        assert len(warn_calls) == 0

    @pytest.mark.asyncio
    async def test_link_warn_fires_only_once(self):
        """Repeated evaluate() with weak RSSI must not repeat the alert."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            st = _state(rssi=LINK_WARN_RSSI - 10)
            await mon.evaluate(1, st)
            await mon.evaluate(1, st)

        warn_calls = [c for c in mock_alert.call_args_list if c.args[1] == "link_warn"]
        assert len(warn_calls) == 1

    @pytest.mark.asyncio
    async def test_link_warn_clears_on_good_rssi(self):
        """Good RSSI must clear the link_warn fired flag."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ):
            await mon.evaluate(1, _state(rssi=LINK_WARN_RSSI - 1))
            assert mon._has_fired(1, "link_warn")

            await mon.evaluate(1, _state(rssi=LINK_WARN_RSSI + 10))
            assert not mon._has_fired(1, "link_warn")

    @pytest.mark.asyncio
    async def test_link_warn_does_not_fire_at_threshold(self):
        """RSSI exactly at LINK_WARN_RSSI — condition is strictly less-than."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            await mon.evaluate(1, _state(rssi=LINK_WARN_RSSI))

        warn_calls = [c for c in mock_alert.call_args_list if c.args[1] == "link_warn"]
        assert len(warn_calls) == 0


# ── GPS warning ───────────────────────────────────────────────────────────────

class TestGPSWarning:

    @pytest.mark.asyncio
    async def test_gps_warn_fires_on_low_sats(self):
        """GPS satellites below GPS_WARN_SATS → gps_warn alert."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            await mon.evaluate(1, _state(sats=GPS_WARN_SATS - 1))

        warn_calls = [c for c in mock_alert.call_args_list if c.args[1] == "gps_warn"]
        assert len(warn_calls) == 1

    @pytest.mark.asyncio
    async def test_gps_warn_fires_only_once(self):
        """Repeated low-sat evaluate() calls must not repeat the alert."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            st = _state(sats=GPS_WARN_SATS - 1)
            await mon.evaluate(1, st)
            await mon.evaluate(1, st)

        warn_calls = [c for c in mock_alert.call_args_list if c.args[1] == "gps_warn"]
        assert len(warn_calls) == 1

    @pytest.mark.asyncio
    async def test_gps_warn_clears_on_good_sats(self):
        """Sufficient satellites must clear the gps_warn flag."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ):
            await mon.evaluate(1, _state(sats=GPS_WARN_SATS - 1))
            assert mon._has_fired(1, "gps_warn")

            await mon.evaluate(1, _state(sats=GPS_WARN_SATS + 2))
            assert not mon._has_fired(1, "gps_warn")

    @pytest.mark.asyncio
    async def test_gps_warn_does_not_fire_at_threshold(self):
        """Exactly GPS_WARN_SATS satellites — condition is strictly less-than."""
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            await mon.evaluate(1, _state(sats=GPS_WARN_SATS))

        warn_calls = [c for c in mock_alert.call_args_list if c.args[1] == "gps_warn"]
        assert len(warn_calls) == 0


# ── Multi-drone isolation ─────────────────────────────────────────────────────

class TestMultiDrone:

    @pytest.mark.asyncio
    async def test_alerts_fire_independently_per_drone(self):
        """
        Drone 1 with low battery must trigger alert.
        Drone 2 with healthy battery must not trigger — even on the same monitor.
        """
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            await mon.evaluate(1, _state(battery=BATTERY_RTL_PCT, mode="AUTO", armed=True))
            await mon.evaluate(2, _state(battery=100, mode="AUTO", armed=True))

        rtl_for_drone_1 = [c for c in mock_alert.call_args_list
                           if c.args[0] == 1 and c.args[1] == "battery_rtl"]
        rtl_for_drone_2 = [c for c in mock_alert.call_args_list
                           if c.args[0] == 2 and c.args[1] == "battery_rtl"]

        assert len(rtl_for_drone_1) == 1
        assert len(rtl_for_drone_2) == 0

    @pytest.mark.asyncio
    async def test_fired_flags_do_not_bleed_across_drones(self):
        """
        Firing an alert for drone 1 must not set the flag for drone 2,
        so drone 2's first low-battery event still triggers an alert.
        """
        mon, mav = _make_monitor()

        with patch(
            "app.modules.drone_control.health_monitor.emit_health_alert",
            new_callable=AsyncMock,
        ) as mock_alert:
            st_low = _state(battery=BATTERY_RTL_PCT, mode="AUTO", armed=True)
            await mon.evaluate(1, st_low)
            await mon.evaluate(2, st_low)   # drone 2 has no prior flag — must fire

        rtl_for_drone_2 = [c for c in mock_alert.call_args_list
                           if c.args[0] == 2 and c.args[1] == "battery_rtl"]
        assert len(rtl_for_drone_2) == 1


# ── Threshold values sanity ───────────────────────────────────────────────────

class TestThresholdValues:
    """Guard against accidental threshold changes in production code."""

    def test_battery_rtl_pct(self):
        assert BATTERY_RTL_PCT == 15

    def test_battery_warn_pct(self):
        assert BATTERY_WARN_PCT == 25

    def test_link_warn_rssi(self):
        assert LINK_WARN_RSSI == 50

    def test_gps_warn_sats(self):
        assert GPS_WARN_SATS == 5

    def test_warn_above_rtl(self):
        """Warning threshold must be higher than the RTL trigger."""
        assert BATTERY_WARN_PCT > BATTERY_RTL_PCT
