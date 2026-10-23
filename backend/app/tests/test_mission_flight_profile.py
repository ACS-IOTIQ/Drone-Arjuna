from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.drone import DroneInstance, DroneType
from app.modules.drone_flight.mission_planner import MissionPlanner
from app.modules.drone_flight.router import (
    _apply_mission_profile,
    _validate_mission_profile,
)
from app.schemas.mission import MissionCreate, MissionUpdate, WaypointCreate
from pymavlink import mavutil


def test_mission_profile_schema_requires_positive_finite_values():
    MissionCreate(name="profile", altitude_m=30, speed_ms=5)
    MissionUpdate(altitude_m=None, speed_ms=None)

    for invalid in (0, -1, float("inf"), float("nan")):
        with pytest.raises(ValidationError):
            MissionCreate(name="profile", altitude_m=invalid)
        with pytest.raises(ValidationError):
            MissionUpdate(speed_ms=invalid)


def test_mission_profile_overrides_route_waypoints_and_preserves_home():
    home = WaypointCreate(
        sequence=0, latitude=17, longitude=78, altitude_m=0,
        speed_ms=None, is_home=True,
    )
    target = WaypointCreate(
        sequence=1, latitude=17.1, longitude=78.1, altitude_m=60,
        altitude_ref="MSL", speed_ms=8,
    )

    result = _apply_mission_profile([home, target], altitude_m=30, speed_ms=5)

    assert result[0].altitude_m == 0
    assert result[0].speed_ms is None
    assert result[1].altitude_m == 30
    assert result[1].altitude_ref == "AGL"
    assert result[1].speed_ms == 5
    # Applying a mission profile creates effective values without mutating
    # the caller's original waypoint objects.
    assert target.altitude_m == 60
    assert target.speed_ms == 8


class _DroneProfileDb:
    async def get(self, model, key):
        if model is DroneInstance:
            return SimpleNamespace(drone_type_id=7)
        if model is DroneType:
            return SimpleNamespace(max_altitude_m=300, max_speed_ms=20)
        raise AssertionError(f"Unexpected model: {model}")


@pytest.mark.asyncio
async def test_mission_profile_is_checked_against_assigned_drone_limits():
    await _validate_mission_profile(_DroneProfileDb(), 12, altitude_m=30, speed_ms=5)

    with pytest.raises(HTTPException) as altitude_error:
        await _validate_mission_profile(_DroneProfileDb(), 12, altitude_m=251, speed_ms=None)
    assert "safe ceiling" in altitude_error.value.detail
    with pytest.raises(HTTPException) as speed_error:
        await _validate_mission_profile(_DroneProfileDb(), 12, altitude_m=None, speed_ms=21)
    assert "maximum" in speed_error.value.detail


def test_mavlink_mission_upload_uses_mission_altitude_and_speed():
    home = SimpleNamespace(
        is_home=True, sequence=0, latitude=17.0, longitude=78.0,
        altitude_m=0, altitude_ref="AGL", speed_ms=None,
    )
    waypoint = SimpleNamespace(
        is_home=False, sequence=1, latitude=17.1, longitude=78.1,
        altitude_m=80, altitude_ref="MSL", speed_ms=9,
        action="none", loiter_time_s=None,
    )

    items = MissionPlanner._build_mavlink_items(
        [home, waypoint], object(), altitude_m=30, speed_ms=5,
    )

    assert len(items) == 3
    speed_item, route_item = items[1], items[2]
    assert speed_item["command"] == mavutil.mavlink.MAV_CMD_DO_CHANGE_SPEED
    assert speed_item["param1"] == 1  # ground speed
    assert speed_item["param2"] == 5
    assert route_item["command"] == mavutil.mavlink.MAV_CMD_NAV_WAYPOINT
    assert route_item["alt"] == 30
    assert route_item["frame"] == mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT


def test_mavlink_upload_keeps_per_waypoint_profile_without_mission_override():
    home = SimpleNamespace(
        is_home=True, sequence=0, latitude=17.0, longitude=78.0,
        altitude_m=0, altitude_ref="AGL", speed_ms=None,
    )
    waypoint = SimpleNamespace(
        is_home=False, sequence=1, latitude=17.1, longitude=78.1,
        altitude_m=45, altitude_ref="AGL", speed_ms=7,
        action="none", loiter_time_s=None,
    )

    items = MissionPlanner._build_mavlink_items([home, waypoint], object())

    assert items[1]["command"] == mavutil.mavlink.MAV_CMD_DO_CHANGE_SPEED
    assert items[1]["param2"] == 7
    assert items[2]["alt"] == 45
