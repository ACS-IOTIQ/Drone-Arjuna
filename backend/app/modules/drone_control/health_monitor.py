"""
Health Monitor — evaluates telemetry state for each drone
and fires automated failsafe responses when thresholds are breached.
Runs as a background asyncio task, wired into the StateManager's subscriber list.
"""
import asyncio
import structlog
from app.core.events import emit_health_alert

log = structlog.get_logger()

# ── Thresholds ─────────────────────────────────────────────────────
BATTERY_RTL_PCT    = 15     # Auto-RTL below this
BATTERY_WARN_PCT   = 25     # Warning alert below this
LINK_WARN_RSSI     = 50     # Weak link warning
GPS_WARN_SATS      = 5      # Low satellite count warning
CPU_WARN_PCT       = 85     # High CPU load warning


class HealthMonitor:
    def __init__(self, mavlink_manager):
        self._mav = mavlink_manager
        # Track which alerts have already fired per drone to avoid flooding
        self._fired: dict[int, set[str]] = {}

    def _has_fired(self, drone_id: int, alert: str) -> bool:
        return alert in self._fired.get(drone_id, set())

    def _mark_fired(self, drone_id: int, alert: str):
        self._fired.setdefault(drone_id, set()).add(alert)

    def _clear_fired(self, drone_id: int, alert: str):
        self._fired.get(drone_id, set()).discard(alert)

    async def evaluate(self, drone_id: int, state: dict):
        """Called by StateManager on every telemetry update."""
        batt = state.get("battery_remaining_pct", -1)
        rssi = state.get("rssi", 255)
        sats = state.get("gps_satellites", 12)
        cpu  = state.get("cpu_load_pct", 0)
        mode = state.get("flight_mode", "")
        armed = state.get("is_armed", False)

        # ── Battery RTL trigger ─────────────────────────────────────
        if batt >= 0 and batt <= BATTERY_RTL_PCT and armed and mode not in ("RTL", "LAND"):
            if not self._has_fired(drone_id, "battery_rtl"):
                log.warning("Low battery — auto RTL", drone_id=drone_id, pct=batt)
                await self._mav.send_command(drone_id, "rtl", {})
                await emit_health_alert(drone_id, "battery_rtl", batt)
                self._mark_fired(drone_id, "battery_rtl")
        elif batt > BATTERY_RTL_PCT + 5:
            self._clear_fired(drone_id, "battery_rtl")

        # ── Battery warning ─────────────────────────────────────────
        if batt >= 0 and batt <= BATTERY_WARN_PCT:
            if not self._has_fired(drone_id, "battery_warn"):
                log.warning("Battery low", drone_id=drone_id, pct=batt)
                await emit_health_alert(drone_id, "battery_warn", batt)
                self._mark_fired(drone_id, "battery_warn")
        elif batt > BATTERY_WARN_PCT + 5:
            self._clear_fired(drone_id, "battery_warn")

        # ── Link quality warning ────────────────────────────────────
        if rssi > 0 and rssi < LINK_WARN_RSSI:
            if not self._has_fired(drone_id, "link_warn"):
                log.warning("Weak link", drone_id=drone_id, rssi=rssi)
                await emit_health_alert(drone_id, "link_warn", rssi)
                self._mark_fired(drone_id, "link_warn")
        else:
            self._clear_fired(drone_id, "link_warn")

        # ── GPS quality warning ─────────────────────────────────────
        if sats < GPS_WARN_SATS:
            if not self._has_fired(drone_id, "gps_warn"):
                log.warning("Low GPS satellites", drone_id=drone_id, sats=sats)
                await emit_health_alert(drone_id, "gps_warn", sats)
                self._mark_fired(drone_id, "gps_warn")
        else:
            self._clear_fired(drone_id, "gps_warn")