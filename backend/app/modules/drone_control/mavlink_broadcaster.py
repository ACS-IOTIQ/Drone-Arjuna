"""
MAVLink Broadcaster
====================
Simulated drones only exist as Python state — no MAVLink packets are ever
generated for them, so external GCS software (ArduPilot Mission Planner,
QGroundControl, etc.) has nothing to connect to.

This module fixes that: for every simulated flight, it encodes real
MAVLink v2 messages (HEARTBEAT, GLOBAL_POSITION_INT, ATTITUDE, VFR_HUD,
SYS_STATUS, GPS_RAW_INT) and sends them over UDP to wherever an external
GCS is listening. Each drone gets its own outbound link tagged with that
drone's mavlink_system_id, so one GCS UDP listener can show every
simulated drone as a separate vehicle — exactly like it would with real
hardware.

Sending is fire-and-forget: if nothing is listening on the target port,
the UDP send simply goes nowhere and costs nothing. No manual "enable"
step is needed — this always runs alongside the simulator.
"""
import math
import time
from typing import Optional
import structlog
from pymavlink import mavutil

from app.config import get_settings

log = structlog.get_logger()

_GPS_FIX_MAP = {"No GPS": 0, "No Fix": 1, "2D Fix": 2, "3D Fix": 3}


def _default_target() -> str:
    cfg = get_settings()
    return f"{cfg.sitl_host}:{cfg.mavlink_broadcast_port}"


def _deg2rad(deg: float) -> float:
    return deg * math.pi / 180.0


class MAVLinkBroadcaster:
    """One outbound UDP MAVLink link per simulated drone_id."""

    def __init__(self, target: Optional[str] = None):
        self._target = target or _default_target()
        self._links: dict[int, object] = {}
        self._last_heartbeat: dict[int, float] = {}

    def _get_link(self, drone_id: int, sys_id: int):
        link = self._links.get(drone_id)
        if link is not None:
            return link
        try:
            link = mavutil.mavlink_connection(
                f"udpout:{self._target}", source_system=sys_id, source_component=1,
            )
            self._links[drone_id] = link
            log.info("MAVLink broadcaster link opened", drone_id=drone_id,
                     sys_id=sys_id, target=self._target)
            return link
        except Exception as e:
            log.warning("MAVLink broadcaster could not open link",
                        drone_id=drone_id, error=str(e))
            return None

    def send(self, drone_id: int, sys_id: int, state: dict):
        link = self._get_link(drone_id, sys_id)
        if link is None:
            return
        try:
            now = time.time()
            mav = link.mav
            armed = bool(state.get("is_armed"))

            if now - self._last_heartbeat.get(drone_id, 0.0) >= 1.0:
                mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_QUADROTOR,
                    mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
                    mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED if armed else 0,
                    0,
                    mavutil.mavlink.MAV_STATE_ACTIVE if armed else mavutil.mavlink.MAV_STATE_STANDBY,
                )
                self._last_heartbeat[drone_id] = now

            t_ms = int(now * 1000) & 0xFFFFFFFF

            mav.global_position_int_send(
                t_ms,
                int(state.get("lat", 0.0) * 1e7),
                int(state.get("lon", 0.0) * 1e7),
                int(state.get("alt_msl", 0.0) * 1000),
                int(state.get("alt_agl", 0.0) * 1000),
                int(state.get("vx", 0.0) * 100),
                int(state.get("vy", 0.0) * 100),
                int(state.get("vz", 0.0) * 100),
                int(state.get("heading", 0.0) % 360 * 100),
            )

            mav.attitude_send(
                t_ms,
                _deg2rad(state.get("roll_deg", 0.0)),
                _deg2rad(state.get("pitch_deg", 0.0)),
                _deg2rad(state.get("yaw_deg", 0.0)),
                0.0, 0.0, 0.0,
            )

            mav.vfr_hud_send(
                float(state.get("airspeed_ms", 0.0)),
                float(state.get("groundspeed_ms", 0.0)),
                int(state.get("heading", 0.0)) % 360,
                int(state.get("throttle_pct", 0.0)),
                float(state.get("alt_msl", 0.0)),
                float(state.get("climb_rate_ms", 0.0)),
            )

            mav.sys_status_send(
                0, 0, 0,
                int(state.get("cpu_load_pct", 0.0) * 10),
                int(state.get("battery_voltage_v", 0.0) * 1000),
                int(state.get("battery_current_a", 0.0) * 100),
                int(state.get("battery_remaining_pct", -1)),
                0, 0, 0, 0, 0, 0, 0,
            )

            mav.gps_raw_int_send(
                int(now * 1e6) & 0xFFFFFFFFFFFFFFFF,
                _GPS_FIX_MAP.get(state.get("gps_fix_type", "No GPS"), 0),
                int(state.get("lat", 0.0) * 1e7),
                int(state.get("lon", 0.0) * 1e7),
                int(state.get("alt_msl", 0.0) * 1000),
                int(state.get("gps_hdop", 99.9) * 100),
                65535,
                int(state.get("groundspeed_ms", 0.0) * 100),
                int(state.get("heading", 0.0) % 360 * 100),
                int(state.get("gps_satellites", 0)),
            )
        except Exception as e:
            log.warning("MAVLink broadcast send failed", drone_id=drone_id, error=str(e))

    def remove(self, drone_id: int):
        link = self._links.pop(drone_id, None)
        self._last_heartbeat.pop(drone_id, None)
        if link is not None:
            try:
                link.close()
            except Exception:
                pass


# Module-level singleton — one broadcaster shared by every simulated flight
mavlink_broadcaster = MAVLinkBroadcaster()
