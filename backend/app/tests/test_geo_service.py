"""
Unit tests for app.modules.drone_flight.geo_service

Pure-logic module: computes mission distance/time/battery estimates
from a list of waypoint-like objects. No DB, no network.
"""
import math
from types import SimpleNamespace

import pytest

from app.modules.drone_flight import geo_service
from app.modules.drone_flight.geo_service import (
    compute_mission_summary,
    CRUISE_SPEED_MS,
    BATTERY_CAP_MAH,
    HOVER_CURRENT_A,
)
from app.utils.geo_utils import haversine_m


def _wp(lat, lon, alt=0.0, speed=None, loiter=None):
    """Build a minimal waypoint-like object matching what geo_service expects."""
    return SimpleNamespace(
        latitude=lat,
        longitude=lon,
        altitude_m=alt,
        speed_ms=speed,
        loiter_time_s=loiter,
    )


class TestEmptyAndSingleton:
    def test_empty_list_returns_zeroed_summary(self):
        summary = compute_mission_summary([])
        assert summary.total_distance_km == 0.0
        assert summary.estimated_flight_time_min == 0.0
        assert summary.estimated_battery_pct == 0.0
        assert summary.waypoint_count == 0

    def test_single_waypoint_returns_zeroed_summary(self):
        summary = compute_mission_summary([_wp(10.0, 20.0)])
        assert summary.total_distance_km == 0.0
        assert summary.estimated_flight_time_min == 0.0
        assert summary.estimated_battery_pct == 0.0
        assert summary.waypoint_count == 1


class TestDistanceComputation:
    def test_two_waypoints_matches_haversine(self):
        a = _wp(12.9716, 77.5946, alt=0.0)   # Bengaluru
        b = _wp(13.0827, 80.2707, alt=0.0)   # Chennai
        summary = compute_mission_summary([a, b])

        expected_m = haversine_m(a.latitude, a.longitude, b.latitude, b.longitude)
        assert summary.total_distance_km == pytest.approx(expected_m / 1000.0, rel=1e-3)
        assert summary.waypoint_count == 2

    def test_altitude_change_increases_distance_over_flat_path(self):
        flat = compute_mission_summary([_wp(0.0, 0.0, alt=0.0), _wp(0.0, 0.1, alt=0.0)])
        climbing = compute_mission_summary([_wp(0.0, 0.0, alt=0.0), _wp(0.0, 0.1, alt=5000.0)])
        assert climbing.total_distance_km > flat.total_distance_km

    def test_3d_distance_uses_pythagoras(self):
        # Same lat/lon (zero horizontal distance), pure vertical climb.
        a = _wp(1.0, 1.0, alt=0.0)
        b = _wp(1.0, 1.0, alt=100.0)
        summary = compute_mission_summary([a, b])
        # Horizontal component ~0, so total distance ~= altitude diff (100 m = 0.1 km)
        assert summary.total_distance_km == pytest.approx(0.1, abs=1e-3)

    def test_multi_leg_mission_sums_all_segments(self):
        wps = [
            _wp(0.0, 0.0),
            _wp(0.0, 0.1),
            _wp(0.1, 0.1),
            _wp(0.1, 0.0),
        ]
        summary = compute_mission_summary(wps)
        expected_m = sum(
            haversine_m(wps[i].latitude, wps[i].longitude,
                        wps[i + 1].latitude, wps[i + 1].longitude)
            for i in range(len(wps) - 1)
        )
        assert summary.total_distance_km == pytest.approx(expected_m / 1000.0, rel=1e-3)


class TestFlightTimeComputation:
    def test_uses_default_cruise_speed_when_speed_not_set(self):
        a = _wp(0.0, 0.0, speed=None)
        b = _wp(0.0, 0.1, speed=None)
        summary = compute_mission_summary([a, b])

        dist_m = haversine_m(a.latitude, a.longitude, b.latitude, b.longitude)
        expected_time_min = (dist_m / CRUISE_SPEED_MS) / 60.0
        assert summary.estimated_flight_time_min == pytest.approx(expected_time_min, rel=1e-2)

    def test_per_waypoint_speed_overrides_default(self):
        slow = compute_mission_summary([_wp(0.0, 0.0, speed=1.0), _wp(0.0, 0.1, speed=1.0)])
        fast = compute_mission_summary([_wp(0.0, 0.0, speed=50.0), _wp(0.0, 0.1, speed=50.0)])
        assert slow.estimated_flight_time_min > fast.estimated_flight_time_min

    def test_loiter_time_is_added_to_destination(self):
        base = compute_mission_summary([_wp(0.0, 0.0), _wp(0.0, 0.1, loiter=0)])
        with_loiter = compute_mission_summary([_wp(0.0, 0.0), _wp(0.0, 0.1, loiter=600)])
        assert with_loiter.estimated_flight_time_min > base.estimated_flight_time_min
        # 600s loiter = 10 extra minutes
        assert with_loiter.estimated_flight_time_min - base.estimated_flight_time_min == pytest.approx(10.0, abs=0.1)

    def test_loiter_only_applies_to_destination_not_origin(self):
        # Loiter set on first waypoint should have no effect (only b.loiter_time_s is read)
        a = _wp(0.0, 0.0, loiter=999)
        b = _wp(0.0, 0.1, loiter=None)
        summary = compute_mission_summary([a, b])
        no_loiter = compute_mission_summary([_wp(0.0, 0.0), _wp(0.0, 0.1)])
        assert summary.estimated_flight_time_min == pytest.approx(no_loiter.estimated_flight_time_min, rel=1e-6)


class TestBatteryEstimate:
    def test_battery_pct_scales_with_flight_time(self):
        short = compute_mission_summary([_wp(0.0, 0.0), _wp(0.0, 0.01)])
        long_ = compute_mission_summary([_wp(0.0, 0.0), _wp(0.0, 5.0)])
        assert long_.estimated_battery_pct > short.estimated_battery_pct

    def test_battery_pct_is_capped_at_100(self):
        # Extremely long mission — battery draw should saturate at 100%.
        a = _wp(0.0, 0.0)
        b = _wp(0.0, 90.0)  # ~quarter of the globe
        summary = compute_mission_summary([a, b])
        assert summary.estimated_battery_pct <= 100.0

    def test_battery_pct_matches_manual_formula_for_known_case(self):
        a = _wp(0.0, 0.0, speed=10.0)
        b = _wp(0.0, 0.1, speed=10.0)
        summary = compute_mission_summary([a, b])

        dist_m = haversine_m(a.latitude, a.longitude, b.latitude, b.longitude)
        total_time_s = dist_m / 10.0
        mah_used = HOVER_CURRENT_A * (total_time_s / 3600.0) * 1000
        expected_pct = min(100.0, (mah_used / BATTERY_CAP_MAH) * 100.0)
        assert summary.estimated_battery_pct == pytest.approx(round(expected_pct, 1), abs=0.15)


class TestWaypointCount:
    def test_waypoint_count_reflects_input_length(self):
        wps = [_wp(0.0, i * 0.01) for i in range(5)]
        summary = compute_mission_summary(wps)
        assert summary.waypoint_count == 5

    def test_rounding_applied_to_outputs(self):
        a = _wp(0.0, 0.0)
        b = _wp(0.0, 0.123456)
        summary = compute_mission_summary([a, b])
        # round(...,2) and round(...,1) applied — verify decimal precision
        assert summary.total_distance_km == round(summary.total_distance_km, 2)
        assert summary.estimated_flight_time_min == round(summary.estimated_flight_time_min, 1)
        assert summary.estimated_battery_pct == round(summary.estimated_battery_pct, 1)
