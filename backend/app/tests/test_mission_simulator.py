"""
Unit tests for the mission simulator's state machine, Mission Planner bridge,
and physics tick.

Unlike test_drone_control_api.py (which exercises simulate/start and
simulate/stop through the HTTP API), these tests drive _SimulatedFlight
directly without going through the API layer or a real MAVLink socket.
"""
import math
from unittest.mock import AsyncMock, MagicMock, patch

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
    """A bare _SimulatedFlight with no StateManager/MAVLink wiring."""
    flight = _SimulatedFlight()
    flight.lat = 12.9716
    flight.lon = 77.5946
    return flight


@pytest.mark.asyncio
async def test_simulated_flight_pushes_state_to_mission_planner_broadcaster():
    flight = make_flight()
    state_mgr = MagicMock()
    state_mgr.init_drone = MagicMock()
    state_mgr.update = AsyncMock()

    with patch("app.modules.drone_control.mavlink_broadcaster.mavlink_broadcaster") as mock_broadcaster:
        await flight.start(
            drone_id=7,
            call_sign="SIM-07",
            waypoints=[{
                "sequence": 1,
                "latitude": 12.9816,
                "longitude": 77.6046,
                "altitude_m": 40.0,
                "speed_ms": 10.0,
                "action": "none",
            }],
            home_lat=12.9716,
            home_lon=77.5946,
            state_mgr=state_mgr,
            mavlink_system_id=23,
            mission_id=901,
        )

        try:
            await flight._push()
        finally:
            await flight.stop()

        mock_broadcaster.set_command_handler.assert_called_once()
        set_handler_args = mock_broadcaster.set_command_handler.call_args.args
        assert set_handler_args[0] == 7
        assert callable(set_handler_args[1])

        state_mgr.update.assert_awaited_once()
        mock_broadcaster.send.assert_called_once()

        send_args = mock_broadcaster.send.call_args.args
        assert send_args[0] == 7
        assert send_args[1] == 23
        assert send_args[2]["call_sign"] == "SIM-07"
        assert send_args[2]["mission_id"] == 901
        assert send_args[2]["sim_phase"] == SimPhase.IDLE.value
        assert send_args[2]["home_lat"] == pytest.approx(12.9716)
        assert send_args[2]["home_lon"] == pytest.approx(77.5946)


def test_haversine_same_point_is_zero():
    assert _haversine_m(12.9716, 77.5946, 12.9716, 77.5946) == pytest.approx(0.0, abs=1e-6)


def test_haversine_known_distance():
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
    assert flight._rtl_route == []


def test_set_mode_land_transitions_to_landing():
    flight = make_flight()
    flight.phase = SimPhase.FLYING
    flight._handle_cmd("set_mode", {"mode": "LAND"})
    assert flight.phase == SimPhase.LANDING


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
    for _ in range(50):
        flight._tick(0.1)
        if flight.phase != SimPhase.TAKEOFF:
            break
    assert flight.phase == SimPhase.FLYING
    assert flight.alt == pytest.approx(5.0)


def test_tick_flying_advances_waypoint_index_when_within_radius():
    flight = make_flight()
    flight.phase = SimPhase.FLYING
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
    assert flight.lat > start_lat

    flight._manual_until = time.monotonic() - 1.0
    moved_again = flight._apply_manual_velocity(0.1)
    assert moved_again is False
    assert flight._manual_vx == 0.0
    assert flight._manual_vy == 0.0
    assert flight._manual_vz == 0.0


def test_collision_avoidance_moves_give_way_drone_clear_of_other_drone():
    manager = SimulationManager()
    manager.get_positions = lambda exclude_drone_id=None: [{
        "drone_id": 1,
        "lat": 12.9716,
        "lon": 77.5946,
        "alt_msl": 80.0,
    }]

    lead = _SimulatedFlight()
    lead.drone_id = 1
    lead.phase = SimPhase.FLYING
    lead.lat = 12.9716
    lead.lon = 77.5946
    lead.alt = 30.0

    follow = _SimulatedFlight()
    follow.drone_id = 2
    follow.phase = SimPhase.FLYING
    follow.lat = 12.9716
    follow.lon = 77.5946
    follow.alt = 30.0
    follow._manager = manager

    follow._apply_collision_avoidance(0.1)

    dist_m = _haversine_m(follow.lat, follow.lon, lead.lat, lead.lon)
    assert dist_m >= 5.0
    assert follow.lat != pytest.approx(lead.lat, abs=1e-12)
    assert follow.lon != pytest.approx(lead.lon, abs=1e-12)


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
    flight.wp_idx = 2
    flight._enter_rtl(shortest_path=False)
    assert flight.phase == SimPhase.RTL
    assert len(flight._rtl_route) == 2
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
    await manager.command(7, "arm", {})


@pytest.mark.asyncio
async def test_manager_stop_is_noop_when_flight_absent():
    manager = SimulationManager()
    await manager.stop(7)


@pytest.mark.asyncio
async def test_manager_stop_all_returns_empty_when_no_flights():
    manager = SimulationManager()
    stopped = await manager.stop_all()
    assert stopped == []


def test_flight_get_status_defaults():
    flight = _SimulatedFlight()
    status = flight.get_status()
    assert status["active"] is False
    assert status["phase"] == SimPhase.IDLE.value
    assert status["drone_id"] is None
    assert status["waypoint_count"] == 0
    assert status["progress"] == 0.0
