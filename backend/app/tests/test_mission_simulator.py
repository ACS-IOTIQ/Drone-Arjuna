"""
Unit tests for the mission simulator's state machine and physics tick.

Unlike test_drone_control_api.py (which exercises simulate/start & simulate/stop
through the HTTP API), these tests drive `_SimulatedFlight` directly — calling
`_handle_cmd`, `_tick`, `_apply_manual_velocity`, `_enter_rtl` and the geometry
helpers without going through the async `_run()` loop, the API layer, or a real
StateManager/MAVLink stack.
"""
import math

import pytest

from app.modules.drone_control.mission_simulator import (
    SimPhase,
    SimulationManager,
    _SimulatedFlight,
    _bearing_deg,
    _haversine_m,
    _move_toward,
)


def make_flight() -> _SimulatedFlight:
    """A bare _SimulatedFlight with no StateManager/MAVLink wiring — safe for
    unit-level state-machine/physics tests that never call start()/_push()."""
    flight = _SimulatedFlight()
    flight.lat = 12.9716
    flight.lon = 77.5946
    return flight


# ── Geometry helpers ───────────────────────────────────────────────────────

def test_haversine_same_point_is_zero():
    assert _haversine_m(12.9716, 77.5946, 12.9716, 77.5946) == pytest.approx(0.0, abs=1e-6)


def test_haversine_known_distance():
    # Roughly 1 degree of latitude ~ 111.19 km at the equator/mid-latitudes.
    dist = _haversine_m(0.0, 0.0, 1.0, 0.0)
    assert dist == pytest.approx(111_195, rel=0.01)


def test_bearing_due_north():
    bearing = _bearing_deg(0.0, 0.0, 1.0, 0.0)
    assert bearing == pytest.approx(0.0, abs=0.5)


def test_bearing_due_east():
    bearing = _bearing_deg(0.0, 0.0, 0.0, 1.0)
    assert bearing == pytest.approx(90.0, abs=0.5)


def test_bearing_due_south():
    bearing = _bearing_deg(1.0, 0.0, 0.0, 0.0)
    assert bearing == pytest.approx(180.0, abs=0.5)


def test_bearing_due_west():
    bearing = _bearing_deg(0.0, 1.0, 0.0, 0.0)
    assert bearing == pytest.approx(270.0, abs=0.5)


def test_move_toward_north_increases_latitude():
    lat, lon = _move_toward(12.0, 77.0, 0.0, 100.0)
    assert lat > 12.0
    assert lon == pytest.approx(77.0, abs=1e-6)


def test_move_toward_east_increases_longitude():
    lat, lon = _move_toward(12.0, 77.0, 90.0, 100.0)
    assert lon > 77.0
    assert lat == pytest.approx(12.0, abs=1e-4)


# ── State machine: arm / disarm ─────────────────────────────────────────────

def test_arm_succeeds_only_from_idle():
    flight = make_flight()
    assert flight.phase == SimPhase.IDLE
    flight._handle_cmd("arm", {})
    assert flight.phase == SimPhase.ARMED
    assert flight.is_armed is True


def test_arm_rejected_when_not_idle():
    flight = make_flight()
    flight.phase = SimPhase.FLYING
    flight._handle_cmd("arm", {})
    assert flight.phase == SimPhase.FLYING
    assert flight.is_armed is False


def test_disarm_succeeds_from_armed():
    flight = make_flight()
    flight.phase = SimPhase.ARMED
    flight.is_armed = True
    flight._handle_cmd("disarm", {})
    assert flight.phase == SimPhase.IDLE
    assert flight.is_armed is False


def test_disarm_succeeds_from_landed():
    flight = make_flight()
    flight.phase = SimPhase.LANDED
    flight.is_armed = True
    flight._handle_cmd("disarm", {})
    assert flight.phase == SimPhase.IDLE
    assert flight.is_armed is False


def test_disarm_rejected_from_flying():
    flight = make_flight()
    flight.phase = SimPhase.FLYING
    flight.is_armed = True
    flight._handle_cmd("disarm", {})
    assert flight.phase == SimPhase.FLYING
    assert flight.is_armed is True


# ── State machine: takeoff ──────────────────────────────────────────────────

def test_takeoff_succeeds_from_idle_and_sets_target_alt():
    flight = make_flight()
    flight._handle_cmd("takeoff", {"altitude": 45.0})
    assert flight.phase == SimPhase.TAKEOFF
    assert flight._target_alt == pytest.approx(45.0)
    assert flight.is_armed is True


def test_takeoff_succeeds_from_armed():
    flight = make_flight()
    flight.phase = SimPhase.ARMED
    flight._handle_cmd("takeoff", {"altitude": 20.0})
    assert flight.phase == SimPhase.TAKEOFF
    assert flight._target_alt == pytest.approx(20.0)


def test_takeoff_uses_first_waypoint_altitude_when_present():
    flight = make_flight()
    flight.waypoints = [{"latitude": 12.98, "longitude": 77.6, "altitude_m": 60.0}]
    flight._handle_cmd("takeoff", {"altitude": 20.0})
    assert flight._target_alt == pytest.approx(60.0)


def test_takeoff_rejected_from_flying():
    flight = make_flight()
    flight.phase = SimPhase.FLYING
    flight._handle_cmd("takeoff", {"altitude": 30.0})
    assert flight.phase == SimPhase.FLYING


# ── State machine: set_mode RTL / LAND ──────────────────────────────────────

def test_set_mode_rtl_always_triggers_enter_rtl():
    flight = make_flight()
    flight.phase = SimPhase.FLYING
    flight.waypoints = [
        {"latitude": 12.98, "longitude": 77.6, "altitude_m": 30.0},
        {"latitude": 12.99, "longitude": 77.61, "altitude_m": 30.0},
    ]
    flight.wp_idx = 1
    flight._handle_cmd("set_mode", {"mode": "RTL"})
    assert flight.phase == SimPhase.RTL
    # shortest_path=True (default from _handle_cmd's set_mode branch) clears the route.
    assert flight._rtl_route == []


def test_set_mode_land_transitions_to_landing():
    flight = make_flight()
    flight.phase = SimPhase.FLYING
    flight._handle_cmd("set_mode", {"mode": "LAND"})
    assert flight.phase == SimPhase.LANDING


# ── State machine: emergency_stop ───────────────────────────────────────────

def test_emergency_stop_forces_landed_and_zeroes_state():
    flight = make_flight()
    flight.phase = SimPhase.FLYING
    flight.is_armed = True
    flight.throttle = 80.0
    flight.groundspeed = 12.0
    flight.airspeed = 12.0
    flight.climb_rate = 3.0
    flight.alt = 55.0
    flight._handle_cmd("emergency_stop", {})
    assert flight.phase == SimPhase.LANDED
    assert flight.is_armed is False
    assert flight.throttle == 0.0
    assert flight.groundspeed == 0.0
    assert flight.airspeed == 0.0
    assert flight.climb_rate == 0.0
    assert flight.alt == 0.0


# ── _tick physics: TAKEOFF → FLYING ─────────────────────────────────────────

def test_tick_takeoff_climbs_toward_target_alt():
    flight = make_flight()
    flight.phase = SimPhase.TAKEOFF
    flight._target_alt = 30.0
    flight.alt = 0.0
    flight._tick(0.1)
    assert 0.0 < flight.alt < 30.0
    assert flight.phase == SimPhase.TAKEOFF


def test_tick_takeoff_reaches_target_and_transitions_to_flying():
    flight = make_flight()
    flight.phase = SimPhase.TAKEOFF
    flight._target_alt = 5.0
    flight.alt = 0.0
    # Climb rate is CLIMB_MS(2.5) * speed_mult(1.0) per second; run enough
    # ticks at dt=0.1s to comfortably exceed the small target altitude.
    for _ in range(50):
        flight._tick(0.1)
        if flight.phase != SimPhase.TAKEOFF:
            break
    assert flight.phase == SimPhase.FLYING
    assert flight.alt == pytest.approx(5.0)


# ── _tick physics: FLYING waypoint advance ──────────────────────────────────

def test_tick_flying_advances_waypoint_index_when_within_radius():
    flight = make_flight()
    flight.phase = SimPhase.FLYING
    # Waypoint essentially co-located with the current position (well within
    # WP_RADIUS_M) and at the same altitude, so a single tick should arrive.
    flight.waypoints = [
        {"latitude": flight.lat + 1e-7, "longitude": flight.lon, "altitude_m": flight.alt},
        {"latitude": flight.lat + 0.01, "longitude": flight.lon, "altitude_m": 30.0},
    ]
    flight.wp_idx = 0
    flight._tick(0.1)
    assert flight.wp_idx == 1


def test_tick_flying_holds_at_paused_when_mission_complete():
    flight = make_flight()
    flight.phase = SimPhase.FLYING
    flight.waypoints = [
        {"latitude": flight.lat + 1e-7, "longitude": flight.lon, "altitude_m": flight.alt},
    ]
    flight.wp_idx = 0
    flight._tick(0.1)
    assert flight.wp_idx == 1
    assert flight.phase == SimPhase.PAUSED


# ── _tick physics: LANDING → LANDED ─────────────────────────────────────────

def test_tick_landing_reduces_alt_to_zero_and_lands():
    flight = make_flight()
    flight.phase = SimPhase.LANDING
    flight.alt = 3.0
    flight.is_armed = True
    for _ in range(200):
        flight._tick(0.1)
        if flight.phase == SimPhase.LANDED:
            break
    assert flight.phase == SimPhase.LANDED
    assert flight.alt == 0.0
    assert flight.is_armed is False


# ── _apply_manual_velocity ──────────────────────────────────────────────────

def test_apply_manual_velocity_moves_and_expires():
    import time

    flight = make_flight()
    flight.is_armed = True
    flight._manual_vx = 5.0
    flight._manual_vy = 0.0
    flight._manual_vz = 0.0
    flight._manual_until = time.monotonic() + 1.0
    start_lat = flight.lat
    moved = flight._apply_manual_velocity(0.1)
    assert moved is True
    assert flight.lat > start_lat  # vx is "north" component

    # Once _manual_until has passed, velocity is cleared and no movement happens.
    flight._manual_until = time.monotonic() - 1.0
    moved_again = flight._apply_manual_velocity(0.1)
    assert moved_again is False
    assert flight._manual_vx == 0.0
    assert flight._manual_vy == 0.0
    assert flight._manual_vz == 0.0


# ── _enter_rtl ───────────────────────────────────────────────────────────────

def test_enter_rtl_shortest_path_clears_route():
    flight = make_flight()
    flight.waypoints = [
        {"latitude": 12.98, "longitude": 77.6, "altitude_m": 30.0},
        {"latitude": 12.99, "longitude": 77.61, "altitude_m": 30.0},
    ]
    flight.wp_idx = 2
    flight._enter_rtl(shortest_path=True)
    assert flight.phase == SimPhase.RTL
    assert flight._rtl_route == []


def test_enter_rtl_retrace_builds_reversed_route_from_visited_waypoints():
    flight = make_flight()
    flight.waypoints = [
        {"latitude": 12.90, "longitude": 77.50, "altitude_m": 10.0},
        {"latitude": 12.91, "longitude": 77.51, "altitude_m": 20.0},
        {"latitude": 12.92, "longitude": 77.52, "altitude_m": 30.0},
    ]
    flight.wp_idx = 2  # first two waypoints visited
    flight._enter_rtl(shortest_path=False)
    assert flight.phase == SimPhase.RTL
    assert len(flight._rtl_route) == 2
    # Reversed order of the visited waypoints: wp[1] then wp[0].
    assert flight._rtl_route[0]["latitude"] == pytest.approx(12.91)
    assert flight._rtl_route[0]["longitude"] == pytest.approx(77.51)
    assert flight._rtl_route[1]["latitude"] == pytest.approx(12.90)
    assert flight._rtl_route[1]["longitude"] == pytest.approx(77.50)


def test_enter_rtl_retrace_with_no_visited_waypoints_is_empty():
    flight = make_flight()
    flight.waypoints = [
        {"latitude": 12.90, "longitude": 77.50, "altitude_m": 10.0},
    ]
    flight.wp_idx = 0
    flight._enter_rtl(shortest_path=False)
    assert flight.phase == SimPhase.RTL
    assert flight._rtl_route == []


# ── SimulationManager with no registered flights ────────────────────────────

def test_manager_is_active_false_when_no_flights():
    manager = SimulationManager()
    assert manager.is_active(1) is False


def test_manager_active_drone_ids_empty_when_no_flights():
    manager = SimulationManager()
    assert manager.active_drone_ids() == []


def test_manager_get_status_no_drone_id_returns_empty_list():
    manager = SimulationManager()
    assert manager.get_status() == []


def test_manager_get_status_specific_drone_returns_none_when_absent():
    manager = SimulationManager()
    assert manager.get_status(drone_id=42) is None


@pytest.mark.asyncio
async def test_manager_command_is_noop_when_flight_absent():
    manager = SimulationManager()
    # Should not raise even though drone_id 7 was never started.
    await manager.command(7, "arm", {})


@pytest.mark.asyncio
async def test_manager_stop_is_noop_when_flight_absent():
    manager = SimulationManager()
    # Should not raise even though drone_id 7 was never started.
    await manager.stop(7)


@pytest.mark.asyncio
async def test_manager_stop_all_returns_empty_when_no_flights():
    manager = SimulationManager()
    stopped = await manager.stop_all()
    assert stopped == []


# ── get_status on an un-started flight ──────────────────────────────────────

def test_flight_get_status_defaults():
    flight = _SimulatedFlight()
    status = flight.get_status()
    assert status["active"] is False
    assert status["phase"] == SimPhase.IDLE.value
    assert status["drone_id"] is None
    assert status["waypoint_count"] == 0
    assert status["progress"] == 0.0
