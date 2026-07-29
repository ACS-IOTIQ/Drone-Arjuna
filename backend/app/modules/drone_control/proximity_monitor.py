"""
Runtime proximity monitor for live/simulated drone separation.
"""
from __future__ import annotations

from app.utils.geo_utils import haversine_m

MIN_SAFE_DISTANCE_M = 200.0


class ProximityMonitor:
    """Computes per-drone proximity alerts from the current in-memory state set."""

    def __init__(self, min_distance_m: float = MIN_SAFE_DISTANCE_M):
        self._min_distance_m = float(min_distance_m)

    def evaluate(self, states: dict[int, dict]) -> dict[int, dict]:
        eligible = {
            drone_id: state
            for drone_id, state in states.items()
            if self._is_positioned(state)
        }

        nearest: dict[int, tuple[int, float]] = {}
        drone_ids = sorted(eligible.keys())
        for idx, drone_id in enumerate(drone_ids[:-1]):
            left = eligible[drone_id]
            for other_id in drone_ids[idx + 1:]:
                right = eligible[other_id]
                distance_m = haversine_m(
                    float(left["lat"]),
                    float(left["lon"]),
                    float(right["lat"]),
                    float(right["lon"]),
                )
                if distance_m > self._min_distance_m:
                    continue
                self._remember_nearest(nearest, drone_id, other_id, distance_m)
                self._remember_nearest(nearest, other_id, drone_id, distance_m)

        updates: dict[int, dict] = {}
        for drone_id in states.keys():
            intruder = nearest.get(drone_id)
            if intruder is None:
                updates[drone_id] = {
                    "proximity_alert": False,
                    "manual_control_required": False,
                    "proximity_distance_m": None,
                    "proximity_intruder_drone_id": None,
                }
                continue

            intruder_id, distance_m = intruder
            updates[drone_id] = {
                "proximity_alert": True,
                "manual_control_required": True,
                "proximity_distance_m": round(distance_m, 1),
                "proximity_intruder_drone_id": intruder_id,
            }

        return updates

    @staticmethod
    def _remember_nearest(
        nearest: dict[int, tuple[int, float]],
        drone_id: int,
        intruder_id: int,
        distance_m: float,
    ) -> None:
        current = nearest.get(drone_id)
        if current is None or distance_m < current[1]:
            nearest[drone_id] = (intruder_id, distance_m)

    @staticmethod
    def _is_positioned(state: dict) -> bool:
        lat = state.get("lat")
        lon = state.get("lon")
        if lat is None or lon is None:
            return False
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return False
        return lat != 0 or lon != 0
