"""
Live waypoint sync tests
========================
POST /api/flight/missions/live-sync/{drone_instance_id}

Pushes the waypoints being drawn/dragged in the planner straight to a connected
drone over MAVLink (no saved Mission needed). No real vehicle is involved: the
MAVLink manager's connection table is replaced with fakes and the blocking mission
upload (`MissionPlanner._send_mission_items`) is replaced with a recorder.

Covers:
  - RBAC: FLIGHT_CONTROLLER and above; viewer / intelligence_analyst -> 403;
    unauthenticated -> 401
  - request validation: bad coordinates, unknown action, malformed body -> 422
  - empty waypoint list -> 400; drone not connected -> 503;
    simulated drone -> 400 (no MAVLink mission protocol); upload failure -> 503
  - government airspace is enforced (restricted zone -> 422 with the errors listed)
  - success: {detail, items}; MAVLink item list built correctly
      (home item first, order by sequence, 1e7 lat/lon scaling, AGL/MSL frames,
       action -> command mapping, speed in param4, loiter time in param1)
  - the upload goes to the right drone's link
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from pymavlink import mavutil

from app.modules.drone_control.mavlink_manager import mavlink_manager
from app.modules.drone_flight.mission_planner import MissionPlanner

URL = "/api/flight/missions/live-sync/{}"
DRONE_ID = 7

# Far from every restricted zone (mid Arabian Sea) and a known airport red zone.
CLEAN = (15.0, 65.0)
DELHI_IGI = (28.5562, 77.1000)


def _auth(user, make_token) -> dict:
    return {"Authorization": f"Bearer {make_token(user.id, user.role)}"}


def _wp(seq, lat=CLEAN[0], lon=CLEAN[1], alt=50.0, **extra):
    return {"sequence": seq, "latitude": lat, "longitude": lon, "altitude_m": alt, **extra}


@pytest.fixture
def uploads(monkeypatch):
    """A connected MAVLink drone (id 7) plus a recorder for every mission upload."""
    mav = MagicMock(name="mav")
    conn = SimpleNamespace(connected=True, transport="udp", mav=mav)
    monkeypatch.setattr(mavlink_manager, "_connections", {DRONE_ID: conn})
    calls: list[tuple] = []
    monkeypatch.setattr(
        MissionPlanner, "_send_mission_items",
        staticmethod(lambda m, items: calls.append((m, items))),
    )
    return SimpleNamespace(calls=calls, mav=mav, conn=conn)


# ══════════════════════════════════════════════════════════════════════
# Access control
# ══════════════════════════════════════════════════════════════════════

async def test_unauthenticated_401(client: AsyncClient):
    r = await client.post(URL.format(DRONE_ID), json={"waypoints": [_wp(1)]})
    assert r.status_code == 401


async def test_viewer_forbidden(client: AsyncClient, viewer_user, make_token, uploads):
    r = await client.post(URL.format(DRONE_ID), json={"waypoints": [_wp(1)]},
                          headers=_auth(viewer_user, make_token))
    assert r.status_code == 403
    assert uploads.calls == []                                   # nothing reached the drone


async def test_intelligence_analyst_forbidden(
    client: AsyncClient, intelligence_analyst_user, make_token, uploads
):
    r = await client.post(URL.format(DRONE_ID), json={"waypoints": [_wp(1)]},
                          headers=_auth(intelligence_analyst_user, make_token))
    assert r.status_code == 403
    assert uploads.calls == []


async def test_flight_controller_allowed(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    r = await client.post(URL.format(DRONE_ID), json={"waypoints": [_wp(1)]},
                          headers=_auth(flight_controller_user, make_token))
    assert r.status_code == 200, r.text


async def test_mission_commander_allowed(
    client: AsyncClient, mission_commander_user, make_token, uploads
):
    r = await client.post(URL.format(DRONE_ID), json={"waypoints": [_wp(1)]},
                          headers=_auth(mission_commander_user, make_token))
    assert r.status_code == 200, r.text


async def test_admin_allowed(client: AsyncClient, admin_user, make_token, uploads):
    r = await client.post(URL.format(DRONE_ID), json={"waypoints": [_wp(1)]},
                          headers=_auth(admin_user, make_token))
    assert r.status_code == 200, r.text


# ══════════════════════════════════════════════════════════════════════
# Request validation
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("bad_wp", [
    _wp(1, lat=91.0),
    _wp(1, lat=-90.5),
    _wp(1, lon=180.5),
    _wp(1, lon=-181.0),
    _wp(1, action="explode"),
    _wp(1, action="loiter"),                                       # loiter needs loiter_time_s
    _wp(1, alt=-5.0),                                              # negative altitude
    _wp(1, altitude_ref="FEET"),
    {"sequence": 1, "latitude": 10.0, "longitude": 10.0},          # altitude_m missing
    {"sequence": "first", "latitude": 10.0, "longitude": 10.0, "altitude_m": 5},
    _wp(1, lat="north"),
])
async def test_invalid_waypoint_is_422(
    client: AsyncClient, flight_controller_user, make_token, uploads, bad_wp
):
    r = await client.post(URL.format(DRONE_ID), json={"waypoints": [bad_wp]},
                          headers=_auth(flight_controller_user, make_token))
    assert r.status_code == 422
    assert uploads.calls == []


@pytest.mark.parametrize("body", [{"waypoints": "nope"}, {"waypoints": [1, 2]}, {"geofence": "polygon"}])
async def test_malformed_body_is_422(
    client: AsyncClient, flight_controller_user, make_token, uploads, body
):
    r = await client.post(URL.format(DRONE_ID), json=body, headers=_auth(flight_controller_user, make_token))
    assert r.status_code == 422


async def test_non_integer_drone_id_is_422(client: AsyncClient, flight_controller_user, make_token):
    r = await client.post(URL.format("abc"), json={"waypoints": [_wp(1)]},
                          headers=_auth(flight_controller_user, make_token))
    assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# Connection state
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("body", [{}, {"waypoints": []}])
async def test_no_waypoints_is_400(
    client: AsyncClient, flight_controller_user, make_token, uploads, body
):
    r = await client.post(URL.format(DRONE_ID), json=body, headers=_auth(flight_controller_user, make_token))
    assert r.status_code == 400
    assert r.json()["detail"] == "No waypoints to sync"
    assert uploads.calls == []


async def test_drone_not_connected_is_503(
    client: AsyncClient, flight_controller_user, make_token, monkeypatch
):
    monkeypatch.setattr(mavlink_manager, "_connections", {})
    r = await client.post(URL.format(DRONE_ID), json={"waypoints": [_wp(1)]},
                          headers=_auth(flight_controller_user, make_token))
    assert r.status_code == 503
    assert r.json()["detail"] == "Drone is not connected"


async def test_connection_that_dropped_is_503(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    uploads.conn.connected = False
    r = await client.post(URL.format(DRONE_ID), json={"waypoints": [_wp(1)]},
                          headers=_auth(flight_controller_user, make_token))
    assert r.status_code == 503
    assert uploads.calls == []


async def test_other_drones_link_is_not_used(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    """Only drone 7 is connected; syncing drone 8 must not upload over drone 7's link."""
    r = await client.post(URL.format(8), json={"waypoints": [_wp(1)]},
                          headers=_auth(flight_controller_user, make_token))
    assert r.status_code == 503
    assert uploads.calls == []


async def test_simulated_drone_is_400(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    uploads.conn.transport = "simulation"
    r = await client.post(URL.format(DRONE_ID), json={"waypoints": [_wp(1)]},
                          headers=_auth(flight_controller_user, make_token))
    assert r.status_code == 400
    assert "MAVLink" in r.json()["detail"]
    assert uploads.calls == []


async def test_connection_without_a_mavlink_handle_is_400(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    uploads.conn.mav = None
    r = await client.post(URL.format(DRONE_ID), json={"waypoints": [_wp(1)]},
                          headers=_auth(flight_controller_user, make_token))
    assert r.status_code == 400


async def test_upload_failure_is_503_with_the_reason(
    client: AsyncClient, flight_controller_user, make_token, uploads, monkeypatch
):
    def _boom(mav, items):
        raise TimeoutError("No MISSION_REQUEST received from drone")

    monkeypatch.setattr(MissionPlanner, "_send_mission_items", staticmethod(_boom))
    r = await client.post(URL.format(DRONE_ID), json={"waypoints": [_wp(1)]},
                          headers=_auth(flight_controller_user, make_token))
    assert r.status_code == 503
    assert "Live waypoint sync failed" in r.json()["detail"]
    assert "No MISSION_REQUEST" in r.json()["detail"]


# ══════════════════════════════════════════════════════════════════════
# Airspace enforcement
# ══════════════════════════════════════════════════════════════════════

async def test_waypoint_inside_a_restricted_zone_is_rejected_422(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    r = await client.post(
        URL.format(DRONE_ID),
        json={"waypoints": [_wp(1), _wp(2, lat=DELHI_IGI[0], lon=DELHI_IGI[1])]},
        headers=_auth(flight_controller_user, make_token),
    )
    assert r.status_code == 422
    errors = r.json()["detail"]["errors"]
    assert errors and any("Waypoint 2" in e for e in errors)     # the offending point is named
    assert uploads.calls == []                                   # nothing was sent to the vehicle


async def test_geofence_enclosing_a_restricted_zone_is_rejected_422(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    lat, lon = DELHI_IGI
    d = 0.5
    ring = [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]
    r = await client.post(
        URL.format(DRONE_ID),
        json={"waypoints": [_wp(1)], "geofence": {"type": "Polygon", "coordinates": [ring]}},
        headers=_auth(flight_controller_user, make_token),
    )
    assert r.status_code == 422
    assert r.json()["detail"]["errors"]
    assert uploads.calls == []


async def test_waypoints_in_clear_airspace_are_accepted(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    r = await client.post(URL.format(DRONE_ID), json={"waypoints": [_wp(1), _wp(2, lat=15.01)]},
                          headers=_auth(flight_controller_user, make_token))
    assert r.status_code == 200
    assert len(uploads.calls) == 1


# ══════════════════════════════════════════════════════════════════════
# Success path & the MAVLink items that are sent
# ══════════════════════════════════════════════════════════════════════

async def test_success_response_reports_item_count(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    r = await client.post(
        URL.format(DRONE_ID),
        json={"waypoints": [_wp(1), _wp(2), _wp(3)]},
        headers=_auth(flight_controller_user, make_token),
    )
    assert r.status_code == 200, r.text
    # no waypoint is flagged as home -> the first one is duplicated as MAVLink item 0
    assert r.json() == {"detail": "Waypoints synced to drone", "items": 4}


async def test_upload_goes_to_the_drones_own_mavlink_link(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    await client.post(URL.format(DRONE_ID), json={"waypoints": [_wp(1)]},
                      headers=_auth(flight_controller_user, make_token))
    (mav_used, _items), = uploads.calls
    assert mav_used is uploads.mav


async def test_explicit_home_waypoint_is_item_zero_and_not_repeated(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    r = await client.post(
        URL.format(DRONE_ID),
        json={"waypoints": [
            _wp(1, lat=15.01, lon=65.01),
            _wp(2, lat=15.00, lon=65.00, alt=0.0, is_home=True),
            _wp(3, lat=15.02, lon=65.02),
        ]},
        headers=_auth(flight_controller_user, make_token),
    )
    assert r.status_code == 200
    assert r.json()["items"] == 3                                 # home + the two others, no duplicate
    items = uploads.calls[0][1]
    assert [i["seq"] for i in items] == [0, 1, 2]
    assert items[0]["lat"] == int(15.00 * 1e7) and items[0]["lon"] == int(65.00 * 1e7)
    assert items[0]["alt"] == 0.0
    assert items[0]["command"] == mavutil.mavlink.MAV_CMD_NAV_WAYPOINT


async def test_items_follow_sequence_order_not_input_order(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    await client.post(
        URL.format(DRONE_ID),
        json={"waypoints": [
            _wp(3, lat=15.03), _wp(1, lat=15.01, is_home=True), _wp(2, lat=15.02),
        ]},
        headers=_auth(flight_controller_user, make_token),
    )
    items = uploads.calls[0][1]
    assert [i["lat"] for i in items] == [int(15.01 * 1e7), int(15.02 * 1e7), int(15.03 * 1e7)]


async def test_coordinates_are_scaled_to_1e7_integers(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    await client.post(
        URL.format(DRONE_ID),
        json={"waypoints": [_wp(1, lat=15.1234567, lon=65.7654321, alt=123.5, is_home=True)]},
        headers=_auth(flight_controller_user, make_token),
    )
    item = uploads.calls[0][1][0]
    assert isinstance(item["lat"], int) and isinstance(item["lon"], int)
    assert item["lat"] == int(15.1234567 * 1e7)
    assert item["lon"] == int(65.7654321 * 1e7)
    assert item["alt"] == 123.5


async def test_altitude_reference_selects_the_mavlink_frame(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    await client.post(
        URL.format(DRONE_ID),
        json={"waypoints": [
            _wp(1, is_home=True),
            _wp(2, altitude_ref="AGL"),
            _wp(3, altitude_ref="MSL"),
        ]},
        headers=_auth(flight_controller_user, make_token),
    )
    items = uploads.calls[0][1]
    assert items[0]["frame"] == mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT   # home is always relative
    assert items[1]["frame"] == mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT   # AGL
    assert items[2]["frame"] == mavutil.mavlink.MAV_FRAME_GLOBAL_INT                # MSL


async def test_actions_map_to_mavlink_commands(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    r = await client.post(
        URL.format(DRONE_ID),
        json={"waypoints": [
            _wp(1, is_home=True),
            _wp(2, action="none", speed_ms=12.0),
            _wp(3, action="loiter", loiter_time_s=25.0),
            _wp(4, action="photo"),
            _wp(5, action="rtl"),
            _wp(6, action="land"),
            _wp(7, action="survey"),                              # no dedicated command -> plain waypoint
        ]},
        headers=_auth(flight_controller_user, make_token),
    )
    assert r.status_code == 200, r.text
    by_seq = {i["seq"]: i for i in uploads.calls[0][1]}
    m = mavutil.mavlink

    # item 0 is home; the rest follow the sequence numbers 2..7 as items 1..6
    assert by_seq[1]["command"] == m.MAV_CMD_NAV_WAYPOINT
    assert by_seq[1]["param4"] == 12.0                            # cruise speed rides in param4

    assert by_seq[2]["command"] == m.MAV_CMD_NAV_LOITER_TIME
    assert by_seq[2]["param1"] == 25.0                            # loiter seconds

    assert by_seq[3]["command"] == m.MAV_CMD_DO_DIGICAM_CONTROL
    assert by_seq[3]["param4"] == 1
    assert by_seq[4]["command"] == m.MAV_CMD_NAV_RETURN_TO_LAUNCH
    assert by_seq[5]["command"] == m.MAV_CMD_NAV_LAND
    assert by_seq[6]["command"] == m.MAV_CMD_NAV_WAYPOINT


async def test_loiter_without_a_time_is_rejected_by_the_schema(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    r = await client.post(
        URL.format(DRONE_ID),
        json={"waypoints": [_wp(1, action="loiter")]},
        headers=_auth(flight_controller_user, make_token),
    )
    assert r.status_code == 422
    assert "loiter_time_s" in r.text
    assert uploads.calls == []


def test_loiter_defaults_to_ten_seconds_when_the_time_is_missing():
    """Unreachable through the API (the schema requires a time) but kept as a safety net
    for waypoints that come from the database."""
    wp = SimpleNamespace(action="loiter", loiter_time_s=None, speed_ms=None)
    cmd, p1, *_ = MissionPlanner._action_to_mavlink(wp)
    assert cmd == mavutil.mavlink.MAV_CMD_NAV_LOITER_TIME
    assert p1 == 10


async def test_waypoint_without_speed_sends_zero_speed(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    await client.post(
        URL.format(DRONE_ID),
        json={"waypoints": [_wp(1, is_home=True), _wp(2)]},
        headers=_auth(flight_controller_user, make_token),
    )
    assert uploads.calls[0][1][1]["param4"] == 0


async def test_every_item_is_marked_not_current_and_has_consecutive_sequence_numbers(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    await client.post(
        URL.format(DRONE_ID),
        json={"waypoints": [_wp(i, lat=15.0 + i / 100) for i in range(1, 6)]},
        headers=_auth(flight_controller_user, make_token),
    )
    items = uploads.calls[0][1]
    assert [i["seq"] for i in items] == list(range(len(items)))
    assert all(i["current"] == 0 for i in items)
    required = {"seq", "frame", "command", "current", "lat", "lon", "alt",
                "param1", "param2", "param3", "param4"}
    assert all(required <= set(i) for i in items)


async def test_each_call_resends_the_whole_list(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    """MAVLink has no incremental update: every debounced sync is a full upload."""
    hdrs = _auth(flight_controller_user, make_token)
    await client.post(URL.format(DRONE_ID), json={"waypoints": [_wp(1), _wp(2)]}, headers=hdrs)
    await client.post(URL.format(DRONE_ID), json={"waypoints": [_wp(1), _wp(2), _wp(3)]}, headers=hdrs)
    first, second = uploads.calls
    assert len(first[1]) == 3 and len(second[1]) == 4


async def test_geofence_is_not_sent_to_the_vehicle(
    client: AsyncClient, flight_controller_user, make_token, uploads
):
    """The geofence only feeds the airspace check; it is never part of the mission items."""
    lat, lon = CLEAN
    ring = [[lon, lat], [lon + 0.1, lat], [lon + 0.1, lat + 0.1], [lon, lat + 0.1], [lon, lat]]
    r = await client.post(
        URL.format(DRONE_ID),
        json={"waypoints": [_wp(1)], "geofence": {"type": "Polygon", "coordinates": [ring]}},
        headers=_auth(flight_controller_user, make_token),
    )
    assert r.status_code == 200, r.text
    assert len(uploads.calls[0][1]) == 2                          # home copy + the one waypoint
