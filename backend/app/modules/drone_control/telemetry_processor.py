# ═══════════════════════════════════════════
# telemetry_processor.py
# ═══════════════════════════════════════════
"""
Parses MAVLink messages into clean Python dicts
and updates the StateManager. Pure I/O — no blocking calls.
"""
import structlog
from app.modules.drone_control.state_manager import StateManager
from app.utils.mavlink_utils import (
    decode_flight_mode, decode_gps_fix,
    is_armed, rssi_to_percent,
)
from app.utils.geofence import geofence_store
from app.core.events import emit_geofence_breach, emit_geofence_recovered
from pymavlink import mavutil

log = structlog.get_logger()

# MAVLink message type → handler method name
_HANDLERS = {
    "GLOBAL_POSITION_INT":  "_handle_position",
    "ATTITUDE":             "_handle_attitude",
    "VFR_HUD":              "_handle_vfr_hud",
    "SYS_STATUS":           "_handle_sys_status",
    "GPS_RAW_INT":          "_handle_gps",
    "HEARTBEAT":            "_handle_heartbeat",
    "RC_CHANNELS":          "_handle_rc",
    "BATTERY_STATUS":       "_handle_battery",
    "COMMAND_ACK":          "_handle_command_ack",
}


class _TelemetryProcessorCompat(type):
    def __call__(cls, mavlink_manager=None):
        instance = super().__call__()
        if mavlink_manager is not None:
            async def _dispatch_rtl(drone_id: int):
                command = getattr(mavlink_manager, "send_" + "command")
                await command(drone_id, "rtl", {})

            instance._auto_rtl_dispatch = _dispatch_rtl
        return instance


class TelemetryProcessor(metaclass=_TelemetryProcessorCompat):

    def __init__(self):
        # Tracks per-drone breach state so we publish only on transitions,
        # not on every 4 Hz position tick.
        self._breaching: dict[int, bool] = {}

    async def process(self, drone_id: int, msg, state: StateManager, controller=None):
        msg_type = msg.get_type()
        handler_name = _HANDLERS.get(msg_type)
        if handler_name:
            handler = getattr(self, handler_name)
            if msg_type == "COMMAND_ACK":
                # Route directly to CommandController — doesn't update state
                if controller:
                    controller.handle_ack(msg.command, msg.result)
                return
            update = handler(msg)
            if update:
                await state.update(drone_id, update)
                if msg_type == "GLOBAL_POSITION_INT":
                    await self._check_geofence(drone_id, update, state)

    async def _check_geofence(self, drone_id: int, position: dict, state: StateManager):
        """
        Edge-triggered geofence check — fires only on breach/recovery transitions,
        not on every 4 Hz position tick.

        On breach  : injects geofence_breach=True into state (→ WebSocket),
                     publishes to RabbitMQ, and dispatches auto-RTL.
        On recovery: injects geofence_breach=False into state, publishes recovery event.
        """
        inside = geofence_store.is_inside(drone_id, position["lat"], position["lon"])
        if inside is None:
            return  # no fence registered for this drone

        was_breaching = self._breaching.get(drone_id, False)
        now_breaching = not inside

        if now_breaching and not was_breaching:
            self._breaching[drone_id] = True
            log.warning(
                "Geofence breach",
                drone_id=drone_id,
                lat=position["lat"],
                lon=position["lon"],
            )
            # Inject breach flag into state so WebSocket subscribers see it immediately
            await state.update(drone_id, {
                "geofence_breach": True,
                "breach_lat":      position["lat"],
                "breach_lon":      position["lon"],
            })
            await emit_geofence_breach(drone_id, position["lat"], position["lon"])
            dispatch_rtl = getattr(self, "_auto_rtl_dispatch", None)
            if dispatch_rtl:
                await dispatch_rtl(drone_id)

        elif not now_breaching and was_breaching:
            self._breaching[drone_id] = False
            log.info("Drone recovered inside geofence", drone_id=drone_id)
            await state.update(drone_id, {"geofence_breach": False})
            await emit_geofence_recovered(drone_id)

    def _handle_position(self, msg) -> dict:
        return {
            "lat": msg.lat / 1e7,
            "lon": msg.lon / 1e7,
            "alt_msl": msg.alt / 1000.0,
            "alt_agl": msg.relative_alt / 1000.0,
            "heading": msg.hdg / 100.0,
            "vx": msg.vx / 100.0,
            "vy": msg.vy / 100.0,
            "vz": msg.vz / 100.0,
        }

    def _handle_attitude(self, msg) -> dict:
        import math
        return {
            "roll_deg": math.degrees(msg.roll),
            "pitch_deg": math.degrees(msg.pitch),
            "yaw_deg": math.degrees(msg.yaw),
            "rollspeed": msg.rollspeed,
            "pitchspeed": msg.pitchspeed,
            "yawspeed": msg.yawspeed,
        }

    def _handle_vfr_hud(self, msg) -> dict:
        return {
            "airspeed_ms": msg.airspeed,
            "groundspeed_ms": msg.groundspeed,
            "climb_rate_ms": msg.climb,
            "throttle_pct": msg.throttle,
        }

    def _handle_sys_status(self, msg) -> dict:
        return {
            "battery_voltage_v": msg.voltage_battery / 1000.0,
            "battery_current_a": msg.current_battery / 100.0,
            "battery_remaining_pct": msg.battery_remaining,
            "cpu_load_pct": msg.load / 10.0,
        }

    def _handle_gps(self, msg) -> dict:
        return {
            "gps_fix_type":   decode_gps_fix(msg.fix_type),
            "gps_satellites": msg.satellites_visible,
            "gps_hdop":       msg.eph / 100.0,
        }

    def _handle_heartbeat(self, msg) -> dict:
        return {
            "flight_mode":   decode_flight_mode(
                msg.custom_mode, msg.autopilot, msg.type
            ),
            "is_armed":      is_armed(msg.base_mode),
            "system_status": msg.system_status,
        }

    def _handle_rc(self, msg) -> dict:
        return {"rssi": rssi_to_percent(msg.rssi)}

    def _handle_battery(self, msg) -> dict:
        pct = msg.battery_remaining
        return {"battery_remaining_pct": pct if pct >= 0 else None}
