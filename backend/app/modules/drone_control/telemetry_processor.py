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


class TelemetryProcessor:

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
