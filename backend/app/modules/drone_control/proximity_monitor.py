"""
Runtime proximity monitor for live/simulated drone separation.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.utils.geo_utils import haversine_m

MIN_SAFE_DISTANCE_M = 250.0
# A live drone (real or simulated) pushes telemetry at 10 Hz — anything that
# hasn't updated in the last few seconds is a stale/orphaned StateManager entry
# (an old sim that finished and was never stopped, a dropped real connection,
# etc.), not something actually flying "here" right now. Comparing a moving
# drone's live position against a frozen one produces phantom 0 m "collisions"
# with a drone that isn't really there — so stale entries must be excluded
# from proximity evaluation entirely.
MAX_POSITION_AGE_S = 5.0


class ProximityMonitor:
    """Computes per-drone proximity alerts from the current in-memory state set."""

    def __init__(self, min_distance_m: float = MIN_SAFE_DISTANCE_M, max_age_s: float = MAX_POSITION_AGE_S):
        self._min_distance_m = float(min_distance_m)
        self._max_age_s = float(max_age_s)

    def evaluate(self, states: dict[int, dict]) -> dict[int, dict]:
        eligible = {
            drone_id: state
            for drone_id, state in states.items()
            if self._is_positioned(state) and self._is_fresh(state)
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

    def _is_fresh(self, state: dict) -> bool:
        last_updated = state.get("last_updated")
        if not last_updated:
            return False
        try:
            updated_at = datetime.fromisoformat(last_updated)
        except (TypeError, ValueError):
            return False
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age_s = (datetime.now(timezone.utc) - updated_at).total_seconds()
        return age_s <= self._max_age_s
