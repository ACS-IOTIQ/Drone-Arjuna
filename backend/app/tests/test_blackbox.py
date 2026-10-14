"""
Tests for the black box (drone issue recorder).

Covers:
  - edge-triggered start/clear events for battery, link, GPS, CPU, geofence, proximity
  - battery two-tier behaviour and hysteresis
  - mode-change and arm/disarm transitions
  - per-drone isolation
  - forget() / StateManager.on_remove reset (reconnect re-logs active issues)
  - record_event(): insert payload, snapshot content, failure swallowed
  - HealthMonitor auto-RTL writes a black-box record

No database is used — record_event is mocked or TSSessionLocal is patched.
"""
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.drone_control.blackbox import BlackBox
from app.modules.drone_control.health_monitor import HealthMonitor
from app.modules.drone_control.state_manager import StateManager

# Same package-shadowing caveat as test_data_recorder.py — fetch real modules.
blackbox_module = sys.modules["app.modules.drone_control.blackbox"]
health_module = sys.modules["app.modules.drone_control.health_monitor"]

pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state(**overrides) -> dict:
    base = {
        "battery_remaining_pct": 80,
        "rssi": 90,
        "gps_satellites": 10,
        "cpu_load_pct": 20.0,
        "flight_mode": "AUTO",
        "is_armed": True,
        "lat": 12.97,
        "lon": 77.59,
        "alt_agl": 100.0,
    }
    base.update(overrides)
    return base


def _bb() -> tuple[BlackBox, AsyncMock]:
    """BlackBox with record_event mocked; returns (box, mock)."""
    box = BlackBox()
    box.record_event = AsyncMock()
    return box, box.record_event


def _types(mock: AsyncMock) -> list[str]:
    return [c.args[1] for c in mock.await_args_list]


def _severity(mock: AsyncMock, event_type: str) -> str:
    return next(c.args[2] for c in mock.await_args_list if c.args[1] == event_type)


def _mock_session() -> AsyncMock:
    s = AsyncMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=False)
    s.execute = AsyncMock()
    s.commit = AsyncMock()
    return s


# ── Healthy drone ─────────────────────────────────────────────────────────────

async def test_healthy_drone_records_nothing():
    box, rec = _bb()
    for _ in range(5):
        await box.evaluate(1, _state())
    rec.assert_not_awaited()


# ── Battery ───────────────────────────────────────────────────────────────────

async def test_battery_warn_fires_once_not_every_tick():
    box, rec = _bb()
    for pct in (24, 23, 22, 21):
        await box.evaluate(1, _state(battery_remaining_pct=pct))
    assert _types(rec) == ["battery_warn"]
    assert _severity(rec, "battery_warn") == "warning"


async def test_battery_critical_is_critical_severity():
    box, rec = _bb()
    await box.evaluate(1, _state(battery_remaining_pct=14))
    assert "battery_critical" in _types(rec)
    assert _severity(rec, "battery_critical") == "critical"


async def test_battery_sequence_warn_critical_then_clears_with_hysteresis():
    box, rec = _bb()
    for pct in (80, 24, 14, 16, 22, 31):
        await box.evaluate(1, _state(battery_remaining_pct=pct))
    # 16 is within hysteresis of critical (15+5=20) → no clear yet;
    # 22 clears critical; 31 (> 25+5) clears warn.
    assert _types(rec) == [
        "battery_warn",
        "battery_critical",
        "battery_critical_cleared",
        "battery_warn_cleared",
    ]


async def test_battery_hovering_at_threshold_does_not_flap():
    box, rec = _bb()
    for pct in (25, 26, 25, 27, 25, 28):
        await box.evaluate(1, _state(battery_remaining_pct=pct))
    assert _types(rec) == ["battery_warn"]


async def test_unknown_battery_is_ignored():
    box, rec = _bb()
    await box.evaluate(1, _state(battery_remaining_pct=-1))
    rec.assert_not_awaited()


# ── Link / GPS / CPU ──────────────────────────────────────────────────────────

async def test_weak_link_fires_and_clears():
    box, rec = _bb()
    await box.evaluate(1, _state(rssi=30))
    await box.evaluate(1, _state(rssi=30))
    await box.evaluate(1, _state(rssi=90))
    assert _types(rec) == ["link_warn", "link_warn_cleared"]
    assert _severity(rec, "link_warn_cleared") == "resolved"


async def test_zero_rssi_is_not_treated_as_weak_link():
    box, rec = _bb()
    await box.evaluate(1, _state(rssi=0))
    rec.assert_not_awaited()


async def test_low_gps_satellites_fires_and_clears():
    box, rec = _bb()
    await box.evaluate(1, _state(gps_satellites=3))
    await box.evaluate(1, _state(gps_satellites=9))
    assert _types(rec) == ["gps_warn", "gps_warn_cleared"]


async def test_high_cpu_fires_at_threshold():
    box, rec = _bb()
    await box.evaluate(1, _state(cpu_load_pct=85))
    assert _types(rec) == ["cpu_warn"]


# ── Geofence / proximity ──────────────────────────────────────────────────────

async def test_geofence_breach_and_recovery():
    box, rec = _bb()
    await box.evaluate(1, _state(geofence_breach=True))
    await box.evaluate(1, _state(geofence_breach=True))
    await box.evaluate(1, _state(geofence_breach=False))
    assert _types(rec) == ["geofence_breach", "geofence_breach_cleared"]
    assert _severity(rec, "geofence_breach") == "critical"


async def test_proximity_alert_message_names_intruder_and_distance():
    box, rec = _bb()
    await box.evaluate(1, _state(
        proximity_alert=True, proximity_intruder_drone_id=7, proximity_distance_m=120.5,
    ))
    assert _types(rec) == ["proximity_alert"]
    message = rec.await_args_list[0].args[3]
    assert "7" in message and "120.5" in message
    assert rec.await_args_list[0].args[4] == 120.5   # value


# ── Mode / arm ────────────────────────────────────────────────────────────────

async def test_first_state_does_not_log_mode_change():
    box, rec = _bb()
    await box.evaluate(1, _state(flight_mode="AUTO", is_armed=False))
    rec.assert_not_awaited()


async def test_mode_change_and_arm_transitions():
    box, rec = _bb()
    await box.evaluate(1, _state(flight_mode="STABILIZE", is_armed=False))
    await box.evaluate(1, _state(flight_mode="STABILIZE", is_armed=True))
    await box.evaluate(1, _state(flight_mode="RTL", is_armed=True))
    await box.evaluate(1, _state(flight_mode="RTL", is_armed=False))
    assert _types(rec) == ["armed", "mode_change", "disarmed"]
    assert all(c.args[2] == "info" for c in rec.await_args_list)


# ── Isolation / reset ─────────────────────────────────────────────────────────

async def test_drones_are_tracked_independently():
    box, rec = _bb()
    await box.evaluate(1, _state(battery_remaining_pct=20))
    await box.evaluate(2, _state(battery_remaining_pct=20))
    assert [c.args[0] for c in rec.await_args_list] == [1, 2]


async def test_forget_makes_reconnect_relog_active_issue():
    box, rec = _bb()
    await box.evaluate(1, _state(battery_remaining_pct=20))
    box.forget(1)
    await box.evaluate(1, _state(battery_remaining_pct=20))
    assert _types(rec) == ["battery_warn", "battery_warn"]


async def test_forget_does_not_log_phantom_mode_change_on_reconnect():
    box, rec = _bb()
    await box.evaluate(1, _state(flight_mode="AUTO"))
    box.forget(1)
    await box.evaluate(1, _state(flight_mode="LOITER"))
    rec.assert_not_awaited()


async def test_forget_unknown_drone_is_safe():
    BlackBox().forget(999)


async def test_state_manager_remove_drone_triggers_forget():
    sm = StateManager()
    box, rec = _bb()
    sm.on_remove(box.forget)
    sm.subscribe(box.evaluate)
    sm.init_drone(1, "ALPHA")

    await sm.update(1, {"battery_remaining_pct": 20, "rssi": 90, "gps_satellites": 10})
    sm.remove_drone(1)
    sm.init_drone(1, "ALPHA")
    await sm.update(1, {"battery_remaining_pct": 20, "rssi": 90, "gps_satellites": 10})

    assert _types(rec).count("battery_warn") == 2


async def test_state_manager_remove_drone_without_callbacks_is_safe():
    sm = StateManager()
    sm.init_drone(1, "ALPHA")
    sm.remove_drone(1)


# ── record_event persistence ──────────────────────────────────────────────────

async def test_record_event_inserts_row_with_snapshot_and_commits():
    box = BlackBox()
    session = _mock_session()
    state = _state(mission_id=42, gps_fix_type="3D Fix")

    with patch.object(blackbox_module, "TSSessionLocal", return_value=session):
        await box.record_event(1, "battery_warn", "warning", "Battery low: 24%", 24, state)

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()

    stmt = session.execute.await_args.args[0]
    params = stmt.compile().params
    assert params["drone_id"] == 1
    assert params["event_type"] == "battery_warn"
    assert params["severity"] == "warning"
    assert params["value"] == 24.0
    assert params["mission_id"] == 42
    assert params["lat"] == 12.97
    assert params["snapshot"]["battery_remaining_pct"] == 80
    assert params["snapshot"]["gps_fix_type"] == "3D Fix"
    assert "call_sign" not in params["snapshot"]


async def test_record_event_non_numeric_value_stored_as_null():
    box = BlackBox()
    session = _mock_session()
    with patch.object(blackbox_module, "TSSessionLocal", return_value=session):
        await box.record_event(1, "geofence_breach", "critical", "Geofence breach", None, _state())
    params = session.execute.await_args.args[0].compile().params
    assert params["value"] is None


async def test_record_event_without_state_still_writes():
    box = BlackBox()
    session = _mock_session()
    with patch.object(blackbox_module, "TSSessionLocal", return_value=session):
        await box.record_event(1, "auto_rtl_battery", "critical", "x")
    params = session.execute.await_args.args[0].compile().params
    assert params["lat"] is None
    assert params["snapshot"] is None


async def test_record_event_swallows_db_errors():
    box = BlackBox()
    session = _mock_session()
    session.execute = AsyncMock(side_effect=RuntimeError("timescale down"))
    with patch.object(blackbox_module, "TSSessionLocal", return_value=session):
        await box.record_event(1, "battery_warn", "warning", "x", 20, _state())  # must not raise
    session.commit.assert_not_awaited()


async def test_evaluate_survives_db_outage():
    """A logging failure must never break the telemetry listener chain."""
    box = BlackBox()
    session = _mock_session()
    session.execute = AsyncMock(side_effect=RuntimeError("down"))
    with patch.object(blackbox_module, "TSSessionLocal", return_value=session):
        await box.evaluate(1, _state(battery_remaining_pct=10))


# ── HealthMonitor integration ─────────────────────────────────────────────────

async def test_health_monitor_auto_rtl_is_recorded_once():
    mav = MagicMock()
    mav.send_command = AsyncMock()
    hm = HealthMonitor(mav)

    with patch.object(health_module, "emit_health_alert", new=AsyncMock()), \
         patch.object(health_module.blackbox, "record_event", new=AsyncMock()) as rec:
        state = _state(battery_remaining_pct=12)
        await hm.evaluate(1, state)
        await hm.evaluate(1, state)   # latched — must not re-fire

    mav.send_command.assert_awaited_once_with(1, "rtl", {})
    rec.assert_awaited_once()
    args = rec.await_args.args
    assert args[0] == 1
    assert args[1] == "auto_rtl_battery"
    assert args[2] == "critical"
    assert args[4] == 12
