
# ═══════════════════════════════════════════
# state_manager.py
# ═══════════════════════════════════════════
"""
In-memory drone state store. Acts as the hot cache between
the MAVLink reader and the WebSocket broadcaster.
Thread-safe via asyncio locks.
"""
import asyncio
from datetime import datetime, timezone
from typing import Optional, Callable

_DEFAULT_STATE = {
    "lat": 0.0, "lon": 0.0,
    "alt_msl": 0.0, "alt_agl": 0.0, "heading": 0.0,
    "vx": 0.0, "vy": 0.0, "vz": 0.0,
    "roll_deg": 0.0, "pitch_deg": 0.0, "yaw_deg": 0.0,
    "airspeed_ms": 0.0, "groundspeed_ms": 0.0, "climb_rate_ms": 0.0,
    "throttle_pct": 0,
    "battery_voltage_v": 0.0, "battery_current_a": 0.0,
    "battery_remaining_pct": -1,
    "gps_fix_type": "No GPS", "gps_satellites": 0, "gps_hdop": 99.9,
    "flight_mode": "UNKNOWN", "is_armed": False, "system_status": 0,
    "rssi": 0, "cpu_load_pct": 0.0,
    "call_sign": "", "connected": True,
    "last_updated": None,
}


class StateManager:
    def __init__(self):
        self._states: dict[int, dict] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._listeners: list[Callable] = []

    def init_drone(self, drone_id: int, call_sign: str):
        self._states[drone_id] = {**_DEFAULT_STATE, "call_sign": call_sign}
        self._locks[drone_id] = asyncio.Lock()

    def remove_drone(self, drone_id: int):
        self._states.pop(drone_id, None)
        self._locks.pop(drone_id, None)

    async def update(self, drone_id: int, data: dict):
        if drone_id not in self._states:
            return
        async with self._locks[drone_id]:
            self._states[drone_id].update(data)
            self._states[drone_id]["last_updated"] = datetime.now(timezone.utc).isoformat()
        # Notify all WebSocket subscribers
        for fn in self._listeners:
            await fn(drone_id, self._states[drone_id])

    def get(self, drone_id: int) -> Optional[dict]:
        return self._states.get(drone_id)

    def get_all(self) -> dict[int, dict]:
        return dict(self._states)

    def subscribe(self, fn: Callable):
        self._listeners.append(fn)

    def unsubscribe(self, fn: Callable):
        self._listeners.remove(fn)