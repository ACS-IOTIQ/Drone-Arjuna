"""
Unit tests for app.modules.drone_flight.airspace_service

Pure-logic module: static zone data (airports/sensitive sites in India)
plus geometry helpers to detect waypoint/geofence violations. No DB,
no network — all data is hardcoded module constants.
"""
import math

import pytest

from app.modules.drone_flight.airspace_service import (
    AIRPORT_ZONES,
    SENSITIVE_ZONES,
    AirspaceViolation,
    AirspaceCheckResult,
    _haversine_m,
    _segment_min_distance_m,
    _point_in_polygon,
    _geojson_to_ring,
    check_points,
    check_geofence_encloses,
    check_geofence_edges,
    check_waypoint_edges,
    validate_mission_airspace,
)

# Delhi IGI Airport, used throughout as a known red/yellow zone reference.
_DELHI = (28.5562, 77.1000, 5_000, 12_000, "Delhi IGI Airport")
_DELHI_LAT, _DELHI_LON = 28.5562, 77.1000

# Far away, clean point (middle of the Arabian Sea) — should never trigger any zone.
_CLEAN_LAT, _CLEAN_LON = 15.0, 65.0


# ══════════════════════════════════════════════════════════════════
# AirspaceCheckResult / AirspaceViolation
# ══════════════════════════════════════════════════════════════════

class TestAirspaceCheckResult:
    def test_ok_true_when_no_violations(self):
        result = AirspaceCheckResult(violations=[])
        assert result.ok is True
        assert result.error_messages == []

    def test_ok_false_when_violations_present(self):
        v = AirspaceViolation(label="WP1", zone_name="Zone", zone_kind="red", message="boom")
        result = AirspaceCheckResult(violations=[v])
        assert result.ok is False
        assert result.error_messages == ["boom"]


# ══════════════════════════════════════════════════════════════════
# Geometry primitives
# ══════════════════════════════════════════════════════════════════

class TestHaversine:
    def test_zero_distance_for_identical_points(self):
        assert _haversine_m(10.0, 20.0, 10.0, 20.0) == pytest.approx(0.0, abs=1e-6)

    def test_known_distance_delhi_to_mumbai_roughly_correct(self):
        # Delhi ~ (28.6139, 77.2090), Mumbai ~ (19.0760, 72.8777) -> ~1150km actual
        d = _haversine_m(28.6139, 77.2090, 19.0760, 72.8777)
        assert 1_100_000 < d < 1_200_000


class TestSegmentMinDistance:
    def test_point_on_segment_has_zero_distance(self):
        # Midpoint of segment is exactly on the segment.
        dist = _segment_min_distance_m(0.0, 0.0, 0.0, 1.0, 0.0, 0.5)
        assert dist == pytest.approx(0.0, abs=1.0)

    def test_point_off_segment_has_positive_distance(self):
        dist = _segment_min_distance_m(0.0, 0.0, 0.0, 1.0, 1.0, 0.5)
        assert dist > 0

    def test_degenerate_segment_falls_back_to_point_distance(self):
        # A == B: segment has zero length -> distance is direct point-to-point.
        dist = _segment_min_distance_m(1.0, 1.0, 1.0, 1.0, 1.0, 1.01)
        direct = _haversine_m(1.0, 1.0, 1.0, 1.01)
        assert dist == pytest.approx(direct, rel=0.05)

    def test_closest_point_clamped_to_endpoints(self):
        # Point "before" A along the line: closest point should be A itself.
        dist_to_a_area = _segment_min_distance_m(0.0, 0.0, 0.0, 1.0, 0.0, -0.5)
        direct_to_a = _haversine_m(0.0, 0.0, 0.0, -0.5)
        assert dist_to_a_area == pytest.approx(direct_to_a, rel=0.05)


class TestPointInPolygon:
    SQUARE = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]  # (lat, lon)

    def test_point_clearly_inside(self):
        assert _point_in_polygon(0.5, 0.5, self.SQUARE) is True

    def test_point_clearly_outside(self):
        assert _point_in_polygon(5.0, 5.0, self.SQUARE) is False

    def test_point_outside_negative_coords(self):
        assert _point_in_polygon(-1.0, -1.0, self.SQUARE) is False

    def test_degenerate_polygon_two_points(self):
        # Ray casting on a degenerate (line) "polygon" should not crash and
        # is well-defined to return False (no enclosed area).
        line = [(0.0, 0.0), (1.0, 1.0)]
        assert _point_in_polygon(0.5, 0.5, line) is False


class TestGeojsonToRing:
    def test_valid_polygon_extracts_ring_without_closing_vertex(self):
        geofence = {
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
        }
        ring = _geojson_to_ring(geofence)
        assert ring == [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]

    def test_missing_coordinates_returns_none(self):
        assert _geojson_to_ring({}) is None

    def test_malformed_coordinates_returns_none(self):
        assert _geojson_to_ring({"coordinates": "not-a-list"}) is None

    def test_coordinates_not_list_of_lists_returns_none(self):
        assert _geojson_to_ring({"coordinates": [1, 2, 3]}) is None


# ══════════════════════════════════════════════════════════════════
# check_points
# ══════════════════════════════════════════════════════════════════

class TestCheckPoints:
    def test_point_at_airport_centre_is_red_violation(self):
        violations = check_points([(_DELHI_LAT, _DELHI_LON, "WP1")])
        red = [v for v in violations if v.zone_kind == "red" and v.zone_name == "Delhi IGI Airport"]
        assert len(red) == 1
        assert red[0].label == "WP1"
        assert "no-fly zone" in red[0].message

    def test_point_in_yellow_ring_not_red(self):
        # ~8km from Delhi centre: outside 5km red radius, inside 12km yellow radius.
        from app.utils.geo_utils import destination_point
        lat, lon = destination_point(_DELHI_LAT, _DELHI_LON, 90, 8_000)
        violations = check_points([(lat, lon, "WP-yellow")])
        kinds = {(v.zone_name, v.zone_kind) for v in violations if v.zone_name == "Delhi IGI Airport"}
        assert ("Delhi IGI Airport", "yellow") in kinds
        assert ("Delhi IGI Airport", "red") not in kinds

    def test_clean_point_produces_no_violations(self):
        violations = check_points([(_CLEAN_LAT, _CLEAN_LON, "WP-clean")])
        assert violations == []

    def test_sensitive_zone_detected(self):
        lat, lon, radius, name = SENSITIVE_ZONES[0]
        violations = check_points([(lat, lon, "WP-sensitive")])
        sensitive = [v for v in violations if v.zone_kind == "sensitive"]
        assert any(v.zone_name == name for v in sensitive)

    def test_multiple_points_multiple_labels_preserved(self):
        violations = check_points([
            (_DELHI_LAT, _DELHI_LON, "WP1"),
            (_CLEAN_LAT, _CLEAN_LON, "WP2"),
        ])
        labels = {v.label for v in violations}
        assert "WP1" in labels
        assert "WP2" not in labels

    def test_empty_points_list_returns_empty(self):
        assert check_points([]) == []


# ══════════════════════════════════════════════════════════════════
# check_geofence_encloses
# ══════════════════════════════════════════════════════════════════

class TestCheckGeofenceEncloses:
    def test_polygon_enclosing_airport_flagged(self):
        # A big box around Delhi IGI that fully encloses it, with no vertex on the airport.
        d_lat, d_lon = _DELHI_LAT, _DELHI_LON
        ring = [
            (d_lat - 1.0, d_lon - 1.0),
            (d_lat - 1.0, d_lon + 1.0),
            (d_lat + 1.0, d_lon + 1.0),
            (d_lat + 1.0, d_lon - 1.0),
        ]
        violations = check_geofence_encloses(ring)
        assert any(v.zone_name == "Delhi IGI Airport" for v in violations)

    def test_polygon_not_enclosing_anything_clean(self):
        ring = [
            (_CLEAN_LAT - 0.1, _CLEAN_LON - 0.1),
            (_CLEAN_LAT - 0.1, _CLEAN_LON + 0.1),
            (_CLEAN_LAT + 0.1, _CLEAN_LON + 0.1),
            (_CLEAN_LAT + 0.1, _CLEAN_LON - 0.1),
        ]
        assert check_geofence_encloses(ring) == []

    def test_degenerate_ring_below_3_points_returns_empty(self):
        assert check_geofence_encloses([(0.0, 0.0), (1.0, 1.0)]) == []
        assert check_geofence_encloses([]) == []


# ══════════════════════════════════════════════════════════════════
# check_geofence_edges
# ══════════════════════════════════════════════════════════════════

class TestCheckGeofenceEdges:
    def test_edge_passing_near_airport_flagged(self):
        # Edge that runs directly through Delhi IGI's red zone even though
        # both vertices sit outside of it.
        ring = [
            (_DELHI_LAT - 0.2, _DELHI_LON),
            (_DELHI_LAT + 0.2, _DELHI_LON),
            (_DELHI_LAT + 0.2, _DELHI_LON + 0.2),
            (_DELHI_LAT - 0.2, _DELHI_LON + 0.2),
        ]
        violations = check_geofence_edges(ring)
        assert any(v.zone_name == "Delhi IGI Airport" for v in violations)

    def test_ring_far_from_all_zones_clean(self):
        ring = [
            (_CLEAN_LAT - 0.1, _CLEAN_LON - 0.1),
            (_CLEAN_LAT - 0.1, _CLEAN_LON + 0.1),
            (_CLEAN_LAT + 0.1, _CLEAN_LON + 0.1),
            (_CLEAN_LAT + 0.1, _CLEAN_LON - 0.1),
        ]
        assert check_geofence_edges(ring) == []

    def test_ring_below_2_points_returns_empty(self):
        assert check_geofence_edges([(0.0, 0.0)]) == []
        assert check_geofence_edges([]) == []

    def test_no_duplicate_violations_for_same_zone_and_edge(self):
        ring = [
            (_DELHI_LAT - 0.2, _DELHI_LON),
            (_DELHI_LAT + 0.2, _DELHI_LON),
            (_DELHI_LAT + 0.2, _DELHI_LON + 0.2),
            (_DELHI_LAT - 0.2, _DELHI_LON + 0.2),
        ]
        violations = check_geofence_edges(ring)
        # Only one violation kind (red or yellow) recorded per zone per edge index.
        keys = [(v.zone_name, v.zone_kind, v.label) for v in violations]
        assert len(keys) == len(set(keys))


# ══════════════════════════════════════════════════════════════════
# check_waypoint_edges
# ══════════════════════════════════════════════════════════════════

class TestCheckWaypointEdges:
    def test_leg_crossing_airport_flagged(self):
        points = [
            (_DELHI_LAT - 0.2, _DELHI_LON, "A"),
            (_DELHI_LAT + 0.2, _DELHI_LON, "B"),
        ]
        violations = check_waypoint_edges(points)
        assert any(v.zone_name == "Delhi IGI Airport" for v in violations)
        assert "Mission leg A to B" in violations[0].label

    def test_leg_far_from_zones_is_clean(self):
        points = [
            (_CLEAN_LAT, _CLEAN_LON, "A"),
            (_CLEAN_LAT + 0.1, _CLEAN_LON + 0.1, "B"),
        ]
        assert check_waypoint_edges(points) == []

    def test_single_point_returns_empty(self):
        assert check_waypoint_edges([(0.0, 0.0, "A")]) == []

    def test_empty_points_returns_empty(self):
        assert check_waypoint_edges([]) == []


# ══════════════════════════════════════════════════════════════════
# validate_mission_airspace — end-to-end
# ══════════════════════════════════════════════════════════════════

class TestValidateMissionAirspace:
    def test_clean_mission_no_geofence_passes(self):
        waypoints = [
            (_CLEAN_LAT, _CLEAN_LON, "WP1"),
            (_CLEAN_LAT + 0.05, _CLEAN_LON + 0.05, "WP2"),
        ]
        result = validate_mission_airspace(waypoints, geofence=None)
        assert result.ok is True
        assert result.error_messages == []

    def test_waypoint_inside_red_zone_fails(self):
        waypoints = [
            (_DELHI_LAT, _DELHI_LON, "WP1"),
            (_DELHI_LAT + 0.01, _DELHI_LON, "WP2"),
        ]
        result = validate_mission_airspace(waypoints, geofence=None)
        assert result.ok is False
        assert any("no-fly zone" in m for m in result.error_messages)

    def test_geofence_none_skips_geofence_checks(self):
        # Only waypoint checks run when geofence is None — verify no exception
        # and result reflects waypoint-only status.
        waypoints = [(_CLEAN_LAT, _CLEAN_LON, "WP1"), (_CLEAN_LAT, _CLEAN_LON + 0.01, "WP2")]
        result = validate_mission_airspace(waypoints, geofence=None)
        assert isinstance(result, AirspaceCheckResult)
        assert result.ok is True

    def test_invalid_geofence_dict_does_not_crash(self):
        waypoints = [(_CLEAN_LAT, _CLEAN_LON, "WP1"), (_CLEAN_LAT, _CLEAN_LON + 0.01, "WP2")]
        result = validate_mission_airspace(waypoints, geofence={"coordinates": []})
        assert result.ok is True

    def test_geofence_enclosing_airport_fails(self):
        d_lat, d_lon = _DELHI_LAT, _DELHI_LON
        geofence = {
            "type": "Polygon",
            "coordinates": [[
                [d_lon - 1.0, d_lat - 1.0],
                [d_lon + 1.0, d_lat - 1.0],
                [d_lon + 1.0, d_lat + 1.0],
                [d_lon - 1.0, d_lat + 1.0],
                [d_lon - 1.0, d_lat - 1.0],
            ]],
        }
        waypoints = [
            (_CLEAN_LAT, _CLEAN_LON, "WP1"),
            (_CLEAN_LAT + 0.01, _CLEAN_LON, "WP2"),
        ]
        result = validate_mission_airspace(waypoints, geofence=geofence)
        assert result.ok is False
        assert any("encloses" in m for m in result.error_messages)

    def test_geofence_vertex_inside_zone_fails(self):
        # A geofence with one vertex sitting exactly at the Delhi airport centre.
        d_lat, d_lon = _DELHI_LAT, _DELHI_LON
        geofence = {
            "type": "Polygon",
            "coordinates": [[
                [d_lon, d_lat],
                [d_lon + 0.5, d_lat],
                [d_lon + 0.5, d_lat + 0.5],
                [d_lon, d_lat + 0.5],
                [d_lon, d_lat],
            ]],
        }
        waypoints = [(_CLEAN_LAT, _CLEAN_LON, "WP1"), (_CLEAN_LAT, _CLEAN_LON + 0.01, "WP2")]
        result = validate_mission_airspace(waypoints, geofence=geofence)
        assert result.ok is False
        assert any("Geofence vertex" in v.label for v in result.violations)

    def test_clean_geofence_and_waypoints_passes(self):
        geofence = {
            "type": "Polygon",
            "coordinates": [[
                [_CLEAN_LON - 0.1, _CLEAN_LAT - 0.1],
                [_CLEAN_LON + 0.1, _CLEAN_LAT - 0.1],
                [_CLEAN_LON + 0.1, _CLEAN_LAT + 0.1],
                [_CLEAN_LON - 0.1, _CLEAN_LAT + 0.1],
                [_CLEAN_LON - 0.1, _CLEAN_LAT - 0.1],
            ]],
        }
        waypoints = [(_CLEAN_LAT, _CLEAN_LON, "WP1"), (_CLEAN_LAT, _CLEAN_LON + 0.01, "WP2")]
        result = validate_mission_airspace(waypoints, geofence=geofence)
        assert result.ok is True
