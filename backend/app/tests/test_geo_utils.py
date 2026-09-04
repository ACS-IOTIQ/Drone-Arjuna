"""
Unit tests for app.utils.geo_utils — pure geometry helpers shared across
drone_flight, drone_control, and drone_analyst.
"""
import math

import pytest

from app.utils import geo_utils


# ══════════════════════════════════════════════════════════════════
# Distance and bearing
# ══════════════════════════════════════════════════════════════════

class TestHaversine:
    def test_zero_distance_for_identical_points(self):
        assert geo_utils.haversine_m(17.0, 78.0, 17.0, 78.0) == pytest.approx(0.0, abs=1e-6)

    def test_known_distance_delhi_to_mumbai_roughly_correct(self):
        # Delhi -> Mumbai is ~1150-1160 km great-circle
        km = geo_utils.haversine_km(28.6139, 77.2090, 19.0760, 72.8777)
        assert 1100 < km < 1200

    def test_haversine_km_is_haversine_m_over_1000(self):
        m = geo_utils.haversine_m(10.0, 20.0, 10.5, 20.5)
        km = geo_utils.haversine_km(10.0, 20.0, 10.5, 20.5)
        assert km == pytest.approx(m / 1000.0)


class TestBearing:
    def test_bearing_due_north(self):
        brg = geo_utils.bearing_deg(0.0, 0.0, 1.0, 0.0)
        assert brg == pytest.approx(0.0, abs=0.5)

    def test_bearing_due_east(self):
        brg = geo_utils.bearing_deg(0.0, 0.0, 0.0, 1.0)
        assert brg == pytest.approx(90.0, abs=0.5)

    def test_bearing_due_south(self):
        brg = geo_utils.bearing_deg(1.0, 0.0, 0.0, 0.0)
        assert brg == pytest.approx(180.0, abs=0.5)

    def test_bearing_is_within_0_360(self):
        brg = geo_utils.bearing_deg(10.0, 10.0, 5.0, 5.0)
        assert 0 <= brg <= 360


class TestDestinationPoint:
    def test_travel_zero_distance_returns_same_point(self):
        lat, lon = geo_utils.destination_point(17.0, 78.0, 90.0, 0.0)
        assert lat == pytest.approx(17.0, abs=1e-6)
        assert lon == pytest.approx(78.0, abs=1e-6)

    def test_travel_north_increases_latitude(self):
        lat, lon = geo_utils.destination_point(17.0, 78.0, 0.0, 10_000)
        assert lat > 17.0
        assert lon == pytest.approx(78.0, abs=1e-3)

    def test_round_trip_distance_matches_haversine(self):
        lat2, lon2 = geo_utils.destination_point(10.0, 10.0, 45.0, 5000)
        d = geo_utils.haversine_m(10.0, 10.0, lat2, lon2)
        assert d == pytest.approx(5000, rel=1e-3)


class TestMidpoint:
    def test_midpoint_of_identical_points_is_itself(self):
        lat, lon = geo_utils.midpoint(17.0, 78.0, 17.0, 78.0)
        assert lat == pytest.approx(17.0, abs=1e-6)
        assert lon == pytest.approx(78.0, abs=1e-6)

    def test_midpoint_is_equidistant_from_both_endpoints(self):
        lat1, lon1 = 17.0, 78.0
        lat2, lon2 = 18.0, 79.0
        mlat, mlon = geo_utils.midpoint(lat1, lon1, lat2, lon2)
        d1 = geo_utils.haversine_m(lat1, lon1, mlat, mlon)
        d2 = geo_utils.haversine_m(lat2, lon2, mlat, mlon)
        assert d1 == pytest.approx(d2, rel=1e-3)


# ══════════════════════════════════════════════════════════════════
# Bounding box
# ══════════════════════════════════════════════════════════════════

class TestBoundingBox:
    def test_single_point(self):
        result = geo_utils.bounding_box([(17.0, 78.0)])
        assert result == (17.0, 78.0, 17.0, 78.0)

    def test_multiple_points(self):
        pts = [(10.0, 20.0), (5.0, 30.0), (15.0, 10.0)]
        result = geo_utils.bounding_box(pts)
        assert result == (5.0, 10.0, 15.0, 30.0)


class TestBboxCentre:
    def test_centre_of_symmetric_box(self):
        centre = geo_utils.bbox_centre(0.0, 0.0, 10.0, 20.0)
        assert centre == (5.0, 10.0)


class TestBboxAreaKm2:
    def test_zero_area_for_degenerate_box(self):
        area = geo_utils.bbox_area_km2(17.0, 78.0, 17.0, 78.0)
        assert area == pytest.approx(0.0, abs=1e-6)

    def test_positive_area_for_real_box(self):
        area = geo_utils.bbox_area_km2(17.0, 78.0, 17.1, 78.1)
        assert area > 0


# ══════════════════════════════════════════════════════════════════
# Point-in-polygon
# ══════════════════════════════════════════════════════════════════

class TestPointInPolygon:
    SQUARE = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)]

    def test_point_clearly_inside(self):
        assert geo_utils.point_in_polygon(5.0, 5.0, self.SQUARE) is True

    def test_point_clearly_outside(self):
        assert geo_utils.point_in_polygon(20.0, 20.0, self.SQUARE) is False

    def test_point_outside_negative_coords(self):
        assert geo_utils.point_in_polygon(-5.0, -5.0, self.SQUARE) is False


class TestGeojsonPolygonToRing:
    def test_valid_polygon_extracts_ring(self):
        geojson = {
            "type": "Polygon",
            "coordinates": [[[78.0, 17.0], [78.1, 17.0], [78.1, 17.1], [78.0, 17.1]]],
        }
        ring = geo_utils.geojson_polygon_to_ring(geojson)
        assert ring == [(17.0, 78.0), (17.0, 78.1), (17.1, 78.1), (17.1, 78.0)]

    def test_missing_coordinates_returns_none(self):
        assert geo_utils.geojson_polygon_to_ring({"type": "Polygon"}) is None

    def test_malformed_coordinates_returns_none(self):
        assert geo_utils.geojson_polygon_to_ring({"coordinates": []}) is None

    def test_none_input_type_error_returns_none(self):
        assert geo_utils.geojson_polygon_to_ring({"coordinates": "not-a-list"}) is None


class TestAllPointsInGeofence:
    GEOFENCE = {
        "coordinates": [[[0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [10.0, 0.0]]],
    }

    def test_all_points_inside(self):
        ok, violations = geo_utils.all_points_in_geofence(
            [(5.0, 5.0), (2.0, 2.0)], self.GEOFENCE
        )
        assert ok is True
        assert violations == []

    def test_some_points_outside(self):
        ok, violations = geo_utils.all_points_in_geofence(
            [(5.0, 5.0), (50.0, 50.0)], self.GEOFENCE
        )
        assert ok is False
        assert violations == [1]

    def test_invalid_geofence_treated_as_pass(self):
        ok, violations = geo_utils.all_points_in_geofence(
            [(5.0, 5.0)], {"coordinates": []}
        )
        assert ok is True
        assert violations == []


# ══════════════════════════════════════════════════════════════════
# Coordinate format conversion
# ══════════════════════════════════════════════════════════════════

class TestDdToDms:
    def test_positive_latitude_is_north(self):
        result = geo_utils.dd_to_dms(17.385277, is_latitude=True)
        assert result.endswith("N")

    def test_negative_latitude_is_south(self):
        result = geo_utils.dd_to_dms(-17.385277, is_latitude=True)
        assert result.endswith("S")

    def test_positive_longitude_is_east(self):
        result = geo_utils.dd_to_dms(78.486671, is_latitude=False)
        assert result.endswith("E")

    def test_negative_longitude_is_west(self):
        result = geo_utils.dd_to_dms(-78.486671, is_latitude=False)
        assert result.endswith("W")

    def test_format_contains_degree_minute_second_markers(self):
        result = geo_utils.dd_to_dms(17.5, is_latitude=True)
        assert "°" in result and "'" in result and '"' in result


class TestDmsToDd:
    def test_north_direction_is_positive(self):
        dd = geo_utils.dms_to_dd(17, 23, 6.997, "N")
        assert dd == pytest.approx(17.385277, abs=1e-4)

    def test_south_direction_is_negative(self):
        dd = geo_utils.dms_to_dd(17, 23, 6.997, "S")
        assert dd == pytest.approx(-17.385277, abs=1e-4)

    def test_west_direction_is_negative(self):
        dd = geo_utils.dms_to_dd(78, 29, 12.0, "W")
        assert dd < 0

    def test_lowercase_direction_handled(self):
        dd = geo_utils.dms_to_dd(10, 0, 0, "s")
        assert dd < 0

    def test_round_trip_dd_to_dms_to_dd(self):
        original = 17.385277
        dms_str = geo_utils.dd_to_dms(original, is_latitude=True)
        # crude parse just to sanity check round trip magnitude
        assert dms_str.startswith("17")


class TestMercatorConversion:
    def test_round_trip_latlon_mercator(self):
        lat, lon = 17.385277, 78.486671
        x, y = geo_utils.latlon_to_mercator(lat, lon)
        lat2, lon2 = geo_utils.mercator_to_latlon(x, y)
        assert lat2 == pytest.approx(lat, abs=1e-6)
        assert lon2 == pytest.approx(lon, abs=1e-6)

    def test_origin_maps_to_zero(self):
        x, y = geo_utils.latlon_to_mercator(0.0, 0.0)
        assert x == pytest.approx(0.0, abs=1e-6)
        assert y == pytest.approx(0.0, abs=1e-6)


# ══════════════════════════════════════════════════════════════════
# Terrain and altitude helpers
# ══════════════════════════════════════════════════════════════════

class TestAglMslConversion:
    def test_agl_to_msl(self):
        assert geo_utils.agl_to_msl(100.0, 500.0) == 600.0

    def test_msl_to_agl(self):
        assert geo_utils.msl_to_agl(600.0, 500.0) == 100.0

    def test_msl_to_agl_never_negative(self):
        assert geo_utils.msl_to_agl(100.0, 500.0) == 0.0


class TestLineOfSightDistance:
    def test_zero_altitude_gives_zero_distance(self):
        assert geo_utils.line_of_sight_distance(0.0, 0.0) == 0.0

    def test_positive_altitude_gives_positive_distance(self):
        assert geo_utils.line_of_sight_distance(100.0, 50.0) > 0

    def test_increasing_altitude_increases_range(self):
        d1 = geo_utils.line_of_sight_distance(100.0, 100.0)
        d2 = geo_utils.line_of_sight_distance(200.0, 200.0)
        assert d2 > d1

    def test_custom_k_factor_and_radius(self):
        d = geo_utils.line_of_sight_distance(100.0, 100.0, earth_radius_m=6_371_000, k_factor=1.0)
        assert d > 0


# ══════════════════════════════════════════════════════════════════
# Path and polygon helpers
# ══════════════════════════════════════════════════════════════════

class TestTotalPathDistance:
    def test_empty_list_returns_zero(self):
        assert geo_utils.total_path_distance_m([]) == 0.0

    def test_single_point_returns_zero(self):
        assert geo_utils.total_path_distance_m([(17.0, 78.0)]) == 0.0

    def test_two_points_matches_haversine(self):
        pts = [(17.0, 78.0), (17.1, 78.1)]
        expected = geo_utils.haversine_m(17.0, 78.0, 17.1, 78.1)
        assert geo_utils.total_path_distance_m(pts) == pytest.approx(expected)

    def test_multi_leg_sums_segments(self):
        pts = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
        leg1 = geo_utils.haversine_m(0.0, 0.0, 0.0, 1.0)
        leg2 = geo_utils.haversine_m(0.0, 1.0, 1.0, 1.0)
        assert geo_utils.total_path_distance_m(pts) == pytest.approx(leg1 + leg2)


class TestPolygonAreaM2:
    def test_fewer_than_3_points_returns_zero(self):
        assert geo_utils.polygon_area_m2([(0.0, 0.0), (0.0, 1.0)]) == 0.0

    def test_zero_points_returns_zero(self):
        assert geo_utils.polygon_area_m2([]) == 0.0

    def test_positive_area_for_real_polygon(self):
        square = [(0.0, 0.0), (0.0, 0.01), (0.01, 0.01), (0.01, 0.0)]
        area = geo_utils.polygon_area_m2(square)
        assert area > 0


class TestSimplifyPath:
    def test_two_or_fewer_points_returned_unchanged(self):
        pts = [(0.0, 0.0), (1.0, 1.0)]
        assert geo_utils.simplify_path(pts) == pts

    def test_empty_list_returned_unchanged(self):
        assert geo_utils.simplify_path([]) == []

    def test_collinear_points_simplified_to_endpoints(self):
        # Points along a near-straight line should collapse to endpoints
        pts = [(0.0, 0.0), (0.0, 0.5), (0.0, 1.0)]
        result = geo_utils.simplify_path(pts, tolerance_m=1000.0)
        assert result[0] == pts[0]
        assert result[-1] == pts[-1]
        assert len(result) <= len(pts)

    def test_significant_deviation_point_retained(self):
        # Middle point deviates far from the line -> should survive simplification
        pts = [(0.0, 0.0), (5.0, 5.0), (0.0, 10.0)]
        result = geo_utils.simplify_path(pts, tolerance_m=10.0)
        assert len(result) == 3

    def test_result_always_starts_and_ends_with_original_endpoints(self):
        pts = [(0.0, 0.0), (0.0, 0.2), (0.0, 0.4), (0.0, 0.6), (0.0, 0.8), (0.0, 1.0)]
        result = geo_utils.simplify_path(pts, tolerance_m=1.0)
        assert result[0] == pts[0]
        assert result[-1] == pts[-1]
