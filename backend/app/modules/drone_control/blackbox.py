"""
Black box — durable record of drone issues.

Subscribed to StateManager like HealthMonitor/DataRecorder, so it sees every
telemetry update for live and simulated drones alike. It is edge-triggered:
one `drone_events` row is written when an issue starts and one when it
clears, never one per telemetry tick. Each row carries a telemetry snapshot
so the cause can be reviewed after the flight.

Thresholds mirror health_monitor.py. Auto-RTL actions taken elsewhere call
`blackbox.record_event()` directly.
"""
import structlog
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.database import TSSessionLocal
from app.models.telemetry import DroneEvent

log = structlog.get_logger()

BATTERY_CRITICAL_PCT = 15
BATTERY_WARN_PCT     = 25
LINK_WARN_RSSI       = 50
GPS_WARN_SATS        = 5
CPU_WARN_PCT         = 85
HYSTERESIS           = 5   # value must recover this far past the threshold to clear

_SNAPSHOT_FIELDS = (
    "lat", "lon", "alt_agl", "groundspeed_ms", "heading",
    "battery_remaining_pct", "battery_voltage_v", "gps_fix_type", "gps_satellites",
    "gps_hdop", "rssi", "cpu_load_pct", "flight_mode", "is_armed", "mission_id",
)


class BlackBox:
    def __init__(self):
        # drone_id -> set of currently-active issue keys
        self._active: dict[int, set[str]] = {}
        # drone_id -> (flight_mode, is_armed) last seen
        self._last_mode: dict[int, tuple] = {}

    async def evaluate(self, drone_id: int, state: dict):
        """StateManager listener — compares current state against active issues."""
        batt = state.get("battery_remaining_pct", -1)
        rssi = state.get("rssi", 0)
        sats = state.get("gps_satellites", 12)
        cpu  = state.get("cpu_load_pct", 0)

        # Battery is a two-tier issue; only the current tier is "active".
        if batt is not None and batt >= 0:
            tier = None
            if batt <= BATTERY_CRITICAL_PCT:
                tier = "battery_critical"
            elif batt <= BATTERY_WARN_PCT:
                tier = "battery_warn"
            clear = batt > BATTERY_WARN_PCT + HYSTERESIS
            await self._set(drone_id, "battery_critical", tier == "battery_critical",
                            state, "critical", f"Battery critical: {batt}%", batt,
                            clear=batt > BATTERY_CRITICAL_PCT + HYSTERESIS)
            await self._set(drone_id, "battery_warn", tier == "battery_warn",
                            state, "warning", f"Battery low: {batt}%", batt, clear=clear)

        await self._set(drone_id, "link_warn", bool(rssi and 0 < rssi < LINK_WARN_RSSI),
                        state, "warning", f"Weak link: RSSI {rssi}", rssi)
        await self._set(drone_id, "gps_warn", sats is not None and sats < GPS_WARN_SATS,
                        state, "warning", f"Low GPS satellites: {sats}", sats)
        await self._set(drone_id, "cpu_warn", bool(cpu and cpu >= CPU_WARN_PCT),
                        state, "warning", f"High CPU load: {cpu}%", cpu)
        await self._set(drone_id, "geofence_breach", bool(state.get("geofence_breach")),
                        state, "critical", "Geofence breach", None)
        await self._set(
            drone_id, "proximity_alert", bool(state.get("proximity_alert")),
            state, "critical",
            f"Proximity alert: drone {state.get('proximity_intruder_drone_id')} "
            f"at {state.get('proximity_distance_m')} m",
            state.get("proximity_distance_m"),
        )

        # Mode / arm transitions (informational)
        mode, armed = state.get("flight_mode"), bool(state.get("is_armed"))
        prev = self._last_mode.get(drone_id)
        self._last_mode[drone_id] = (mode, armed)
        if prev is not None:
            if mode != prev[0]:
                await self.record_event(drone_id, "mode_change", "info",
                                        f"Mode changed: {prev[0]} → {mode}", state=state)
            if armed != prev[1]:
                await self.record_event(drone_id, "armed" if armed else "disarmed", "info",
                                        "ARMED" if armed else "DISARMED", state=state)

    async def _set(self, drone_id: int, key: str, condition: bool, state: dict,
                   severity: str, message: str, value: Optional[float],
                   clear: Optional[bool] = None):
        """Writes on the inactive→active and active→inactive edges only."""
        active = self._active.setdefault(drone_id, set())
        is_active = key in active
        if condition and not is_active:
            active.add(key)
            await self.record_event(drone_id, key, severity, message, value, state)
        elif is_active and (clear if clear is not None else not condition):
            active.discard(key)
            await self.record_event(drone_id, f"{key}_cleared", "resolved",
                                    f"Cleared: {message}", value, state)

    def forget(self, drone_id: int):
        """Call on disconnect so a reconnect starts with a clean edge state."""
        self._active.pop(drone_id, None)
        self._last_mode.pop(drone_id, None)

    async def record_event(self, drone_id: int, event_type: str, severity: str,
                           message: str, value: Optional[float] = None,
                           state: Optional[dict] = None):
        state = state or {}
        snapshot = {f: state.get(f) for f in _SNAPSHOT_FIELDS if f in state}
        try:
            async with TSSessionLocal() as session:
                await session.execute(pg_insert(DroneEvent).values(
                    recorded_at=datetime.now(timezone.utc),
                    drone_id=drone_id,
                    event_type=event_type,
                    severity=severity,
                    message=message,
                    value=float(value) if isinstance(value, (int, float)) else None,
                    lat=state.get("lat"),
                    lon=state.get("lon"),
                    alt_agl=state.get("alt_agl"),
                    mission_id=state.get("mission_id"),
                    snapshot=snapshot or None,
                ).on_conflict_do_nothing())
                await session.commit()
        except Exception as e:
            # Never let a logging failure disturb the telemetry/failsafe path.
            log.error("Black box write failed", error=str(e),
                      drone_id=drone_id, event_type=event_type)


blackbox = BlackBox()
