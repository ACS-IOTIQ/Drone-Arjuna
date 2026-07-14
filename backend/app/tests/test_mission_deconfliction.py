"""
Mission Deconfliction Tests
============================
Covers:
  A. deconflict_missions() unit tests — pure geometry, no DB
  B. PATCH /api/flight/missions/{mid}/status → "approved" integration tests
     - 409 when active missions conflict
     - 200 when no conflict
     - 200 for non-approved status transitions (no deconfliction run)
"""
import pytest
import pytest_asyncio
from unittest.mock import MagicMock
from httpx import AsyncClient

from app.modules.drone_flight.mission_planner import deconflict_missions
from app.tests.helpers import auth_headers


# ── Shared geometry fixtures ───────────────────────────────────────

def _make_mission(mission_id: int, name: str = None):
    m = MagicMock()
    m.id   = mission_id
    m.name = name or f"Mission-{mission_id}"
    return m


def _make_waypoints(coords: list[tuple[float, float]], mission_id: int = 1):
    """Build mock Waypoint objects from a list of (lat, lon) tuples."""
    wps = []
    for seq, (lat, lon) in enumerate(coords):
        wp = MagicMock()
        wp.mission_id = mission_id
        wp.sequence   = seq
        wp.latitude   = lat
        wp.longitude  = lon
        wp.altitude_m = 100.0
        wps.append(wp)
    return wps


# Bangalore area — two non-overlapping boxes separated by ~20 km
_BOX_A = [
    (12.965, 77.585), (12.975, 77.585),
    (12.975, 77.595), (12.965, 77.595),
]
_BOX_B = [
    (13.100, 77.700), (13.110, 77.700),
    (13.110, 77.710), (13.100, 77.710),
]

# Box that overlaps the centre of BOX_A
_BOX_OVERLAP_A = [
    (12.960, 77.580), (12.980, 77.580),
    (12.980, 77.600), (12.960, 77.600),
]


# ═══════════════════════════════════════════════════════════════════
# Part A — deconflict_missions() unit tests
# ═══════════════════════════════════════════════════════════════════

class TestDeconflictMissions:

    def test_no_conflict_separate_areas(self):
        """Two missions in completely separate boxes must return no conflicts."""
        m1, m2 = _make_mission(1), _make_mission(2)
        result = deconflict_missions([
            (m1, _make_waypoints(_BOX_A, 1)),
            (m2, _make_waypoints(_BOX_B, 2)),
        ])
        assert result == []

    def test_conflict_overlapping_polygons(self):
        """Two missions whose convex hulls overlap must return one conflict entry."""
        m1, m2 = _make_mission(1, "Alpha"), _make_mission(2, "Bravo")
        result = deconflict_missions([
            (m1, _make_waypoints(_BOX_A, 1)),
            (m2, _make_waypoints(_BOX_OVERLAP_A, 2)),
        ])
        assert len(result) == 1
        c = result[0]
        assert c["mission_a_id"] == 1
        assert c["mission_b_id"] == 2
        assert c["mission_a_name"] == "Alpha"
        assert c["mission_b_name"] == "Bravo"
        assert c["overlap_area_km2"] > 0

    def test_single_mission_no_conflict(self):
        """A single mission has nothing to conflict with."""
        m1 = _make_mission(1)
        result = deconflict_missions([(m1, _make_waypoints(_BOX_A, 1))])
        assert result == []

    def test_empty_input(self):
        """Empty list returns empty conflict list."""
        assert deconflict_missions([]) == []

    def test_mission_with_no_waypoints_skipped(self):
        """A mission with no waypoints is silently skipped — no crash."""
        m1, m2 = _make_mission(1), _make_mission(2)
        result = deconflict_missions([
            (m1, []),
            (m2, _make_waypoints(_BOX_A, 2)),
        ])
        assert result == []

    def test_three_missions_two_conflicts(self):
        """
        Three missions where A overlaps B and A overlaps C but B and C are separate.
        Must return exactly two conflict entries.
        """
        m_a = _make_mission(1, "Alpha")
        m_b = _make_mission(2, "Bravo")
        m_c = _make_mission(3, "Charlie")

        # Large box covering both BOX_B and BOX_OVERLAP_A
        big_box = [
            (12.950, 77.560), (13.120, 77.560),
            (13.120, 77.720), (12.950, 77.720),
        ]

        result = deconflict_missions([
            (m_a, _make_waypoints(big_box, 1)),
            (m_b, _make_waypoints(_BOX_B, 2)),
            (m_c, _make_waypoints(_BOX_A, 3)),
        ])
        # big_box overlaps both BOX_B and BOX_A
        assert len(result) == 2
        ids = {(r["mission_a_id"], r["mission_b_id"]) for r in result}
        assert (1, 2) in ids or (2, 1) in ids
        assert (1, 3) in ids or (3, 1) in ids

    def test_identical_missions_conflict(self):
        """Two missions with identical waypoints fully overlap — must conflict."""
        m1, m2 = _make_mission(1), _make_mission(2)
        result = deconflict_missions([
            (m1, _make_waypoints(_BOX_A, 1)),
            (m2, _make_waypoints(_BOX_A, 2)),
        ])
        assert len(result) == 1
        assert result[0]["overlap_area_km2"] > 0

    def test_two_waypoint_missions_non_crossing(self):
        """
        Two-waypoint missions (line segments) that do not cross must not conflict.
        Convex hull of 2 points is a LineString.
        """
        m1, m2 = _make_mission(1), _make_mission(2)
        line_a = [(12.970, 77.585), (12.975, 77.590)]   # NW→SE in box A
        line_b = [(13.100, 77.700), (13.110, 77.710)]   # far away

        result = deconflict_missions([
            (m1, _make_waypoints(line_a, 1)),
            (m2, _make_waypoints(line_b, 2)),
        ])
        assert result == []

    def test_conflict_dict_keys_present(self):
        """Conflict entries must contain all required keys."""
        m1, m2 = _make_mission(10, "X"), _make_mission(20, "Y")
        result = deconflict_missions([
            (m1, _make_waypoints(_BOX_A, 10)),
            (m2, _make_waypoints(_BOX_OVERLAP_A, 20)),
        ])
        assert len(result) == 1
        required = {"mission_a_id", "mission_a_name", "mission_b_id",
                    "mission_b_name", "overlap_area_km2"}
        assert required == set(result[0].keys())

    def test_touching_boundary_not_a_conflict(self):
        """
        Two polygons that share only an edge (boundary touching, no interior overlap)
        must NOT be reported as a conflict.
        """
        m1, m2 = _make_mission(1), _make_mission(2)
        # Box A right edge at lon=77.595; Box C left edge also at lon=77.595
        box_c = [
            (12.965, 77.595), (12.975, 77.595),
            (12.975, 77.605), (12.965, 77.605),
        ]
        result = deconflict_missions([
            (m1, _make_waypoints(_BOX_A, 1)),
            (m2, _make_waypoints(box_c, 2)),
        ])
        assert result == []


# ═══════════════════════════════════════════════════════════════════
# Part B — PATCH /api/flight/missions/{mid}/status integration tests
# ═══════════════════════════════════════════════════════════════════

# Helpers to create missions and waypoints through the API

async def _create_mission(client: AsyncClient, hdrs: dict, waypoints: list,
                           name: str = "Test") -> int:
    resp = await client.post(
        "/api/flight/missions",
        json={
            "name": name,
            "mission_type": "ISR",
            "waypoints": waypoints,
        },
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _set_status(client: AsyncClient, hdrs: dict, mid: int,
                      status: str) -> int:
    resp = await client.patch(
        f"/api/flight/missions/{mid}/status",
        json={"status": status},
        headers=hdrs,
    )
    return resp.status_code


def _wp(seq, lat, lon):
    return {
        "sequence": seq, "latitude": lat, "longitude": lon,
        "altitude_m": 100.0, "is_home": seq == 0,
    }


# Bangalore non-overlapping areas
_API_WPS_A = [_wp(0, 12.965, 77.585), _wp(1, 12.975, 77.595)]
_API_WPS_B = [_wp(0, 13.100, 77.700), _wp(1, 13.110, 77.710)]
_API_WPS_OVERLAP_A = [_wp(0, 12.960, 77.580), _wp(1, 12.980, 77.600)]


async def test_approve_no_conflict_returns_200(
    client: AsyncClient, mission_commander_user, make_token
):
    """Approving a mission with no active conflicts must return 200."""
    hdrs = auth_headers(mission_commander_user, make_token)
    mid = await _create_mission(client, hdrs, _API_WPS_A, "Alpha")
    code = await _set_status(client, hdrs, mid, "approved")
    assert code == 200


async def test_approve_with_conflict_returns_409(
    client: AsyncClient, mission_commander_user, make_token
):
    """
    Approving a mission whose convex hull overlaps an already-approved
    mission must return 409 with a conflict list.
    """
    hdrs = auth_headers(mission_commander_user, make_token)

    # Approve the first mission (BOX_A)
    mid_a = await _create_mission(client, hdrs, _API_WPS_A, "Alpha")
    assert await _set_status(client, hdrs, mid_a, "approved") == 200

    # Attempt to approve overlapping mission — must be blocked
    mid_b = await _create_mission(client, hdrs, _API_WPS_OVERLAP_A, "Bravo")
    resp = await client.patch(
        f"/api/flight/missions/{mid_b}/status",
        json={"status": "approved"},
        headers=hdrs,
    )
    assert resp.status_code == 409
    body = resp.json()
    assert "conflicts" in body["detail"]
    assert len(body["detail"]["conflicts"]) >= 1
    ids = {
        (c["mission_a_id"], c["mission_b_id"])
        for c in body["detail"]["conflicts"]
    }
    # The conflict must involve both missions
    assert any(mid_a in pair and mid_b in pair for pair in ids)


async def test_approve_separate_areas_no_conflict(
    client: AsyncClient, mission_commander_user, make_token
):
    """Two missions in separate areas: both can be approved without conflict."""
    hdrs = auth_headers(mission_commander_user, make_token)

    mid_a = await _create_mission(client, hdrs, _API_WPS_A, "Alpha")
    assert await _set_status(client, hdrs, mid_a, "approved") == 200

    mid_b = await _create_mission(client, hdrs, _API_WPS_B, "Bravo")
    assert await _set_status(client, hdrs, mid_b, "approved") == 200


async def test_non_approved_transition_skips_deconfliction(
    client: AsyncClient, mission_commander_user, make_token
):
    """
    Status transitions to planning/aborted/completed must never trigger
    deconfliction — even if there are active conflicting missions.
    """
    hdrs = auth_headers(mission_commander_user, make_token)

    # Approve a mission to make it "active"
    mid_a = await _create_mission(client, hdrs, _API_WPS_A, "Alpha")
    assert await _set_status(client, hdrs, mid_a, "approved") == 200

    # Set an overlapping mission back to planning — no 409
    mid_b = await _create_mission(client, hdrs, _API_WPS_OVERLAP_A, "Bravo")
    assert await _set_status(client, hdrs, mid_b, "planning") == 200


async def test_approve_conflict_with_executing_mission(
    client: AsyncClient, mission_commander_user, make_token
):
    """
    An "executing" mission is also active — approval of an overlapping
    mission must still return 409.
    """
    hdrs = auth_headers(mission_commander_user, make_token)

    mid_a = await _create_mission(client, hdrs, _API_WPS_A, "Alpha")
    # Set directly to executing (simulating an in-progress mission)
    assert await _set_status(client, hdrs, mid_a, "executing") == 200

    mid_b = await _create_mission(client, hdrs, _API_WPS_OVERLAP_A, "Bravo")
    resp = await client.patch(
        f"/api/flight/missions/{mid_b}/status",
        json={"status": "approved"},
        headers=hdrs,
    )
    assert resp.status_code == 409


async def test_approve_mission_not_found_returns_404(
    client: AsyncClient, mission_commander_user, make_token
):
    """PATCH on a non-existent mission must return 404."""
    hdrs = auth_headers(mission_commander_user, make_token)
    resp = await client.patch(
        "/api/flight/missions/99999/status",
        json={"status": "approved"},
        headers=hdrs,
    )
    assert resp.status_code == 404


async def test_approve_requires_mission_commander(
    client: AsyncClient, flight_controller_user, make_token
):
    """A flight_controller (below mission_commander) must receive 403."""
    hdrs = auth_headers(flight_controller_user, make_token)
    resp = await client.patch(
        "/api/flight/missions/1/status",
        json={"status": "approved"},
        headers=hdrs,
    )
    assert resp.status_code == 403
