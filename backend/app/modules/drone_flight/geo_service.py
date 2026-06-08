"""
Geo computation utilities for mission planning.
Uses geo_utils for core geometry; this module adds
mission-domain logic (battery estimates, summary schema).
"""
import math
from pyproj import Geod
from app.schemas.mission import MissionSummary
from app.utils.geo_utils import haversine_m

_geod = Geod(ellps="WGS84")

# Mission planning constants — imported by mission_planner.py
CRUISE_SPEED_MS = 15.0      # Default cruise speed if not set per waypoint
BATTERY_CAP_MAH = 10000     # Default battery capacity in mAh
HOVER_CURRENT_A = 20.0      # Approximate hover current draw in amps


def compute_mission_summary(waypoints: list) -> MissionSummary:
    if len(waypoints) < 2:
        return MissionSummary(
            total_distance_km=0.0,
            estimated_flight_time_min=0.0,
            estimated_battery_pct=0.0,
            waypoint_count=len(waypoints),
        )

    total_m = 0.0
    total_time_s = 0.0

    for i in range(len(waypoints) - 1):
        a, b = waypoints[i], waypoints[i + 1]
        seg_m = haversine_m(a.latitude, a.longitude, b.latitude, b.longitude)
        # Add altitude change distance
        alt_diff = abs(b.altitude_m - a.altitude_m)
        seg_3d = math.sqrt(seg_m ** 2 + alt_diff ** 2)
        total_m += seg_3d

        speed = a.speed_ms or CRUISE_SPEED_MS
        total_time_s += seg_3d / speed

        # Add loiter time at destination
        if b.loiter_time_s:
            total_time_s += b.loiter_time_s

    total_time_min = total_time_s / 60.0
    # Rough battery estimate: current draw * time
    mah_used = HOVER_CURRENT_A * (total_time_s / 3600.0) * 1000
    battery_pct = min(100.0, (mah_used / BATTERY_CAP_MAH) * 100.0)

    return MissionSummary(
        total_distance_km=round(total_m / 1000.0, 2),
        estimated_flight_time_min=round(total_time_min, 1),
        estimated_battery_pct=round(battery_pct, 1),
        waypoint_count=len(waypoints),
    )