"""
MAVLink Utilities
=================
Shared helpers for MAVLink protocol handling used across
drone_control, drone_flight, and any future modules that
communicate directly with vehicles.

Keeps protocol-level knowledge in one place so individual
modules stay clean of MAVLink constants and string maps.
"""
import math
from typing import Optional
from pymavlink import mavutil


# ══════════════════════════════════════════════════════════════════
# Connection string builders
# ══════════════════════════════════════════════════════════════════

def build_connection_string(
    transport: str,
    host: str = "127.0.0.1",
    port: int = 14550,
    serial_port: str = "/dev/ttyUSB0",
    baud_rate: int = 57600,
) -> str:
    """
    Returns a pymavlink-compatible connection string.

    Transport   String format
    ---------   --------------------------------------------------
    udp         udpin:host:port   (GCS listens, drone sends)
    udp_out     udpout:host:port  (GCS sends, drone listens)
    tcp         tcp:host:port
    serial      /dev/ttyUSB0,57600
    sitl        tcp:127.0.0.1:5760  (ArduPilot SITL default)
    """
    transport = transport.lower().strip()
    if transport == "udp":
        # Always listen on all interfaces so SITL / GCS on any host can reach us.
        # The `host` param is ignored for incoming UDP — we bind 0.0.0.0.
        return f"udpin:0.0.0.0:{port}"
    if transport == "udp_out":
        return f"udpout:{host}:{port}"
    if transport == "tcp":
        return f"tcp:{host}:{port}"
    if transport == "serial":
        return f"{serial_port},{baud_rate}"
    if transport in ("sitl", "hf_serial", "hf_tcp"):
        # sitl   → ArduPilot SITL TCP GCS port (host.docker.internal reaches Windows host)
        # hf_*   → handled as tcp/serial by pymavlink; connection string already built above
        return f"tcp:{host}:{port}"
    raise ValueError(
        f"Unknown transport '{transport}'. "
        f"Expected: udp | udp_out | tcp | serial | sitl"
    )


# ══════════════════════════════════════════════════════════════════
# Flight mode maps
# ══════════════════════════════════════════════════════════════════

# ArduCopter custom mode IDs → human-readable names
ARDUCOPTER_MODES: dict[int, str] = {
    0:  "STABILIZE",
    1:  "ACRO",
    2:  "ALT_HOLD",
    3:  "AUTO",
    4:  "GUIDED",
    5:  "LOITER",
    6:  "RTL",
    7:  "CIRCLE",
    9:  "LAND",
    11: "DRIFT",
    13: "SPORT",
    14: "FLIP",
    15: "AUTOTUNE",
    16: "POSHOLD",
    17: "BRAKE",
    18: "THROW",
    19: "AVOID_ADSB",
    20: "GUIDED_NOGPS",
    21: "SMART_RTL",
    22: "FLOWHOLD",
    23: "FOLLOW",
    24: "ZIGZAG",
    25: "SYSTEMID",
    26: "AUTOROTATE",
    27: "AUTO_RTL",
}

# ArduPlane custom mode IDs → human-readable names
ARDUPLANE_MODES: dict[int, str] = {
    0:  "MANUAL",
    1:  "CIRCLE",
    2:  "STABILIZE",
    3:  "TRAINING",
    4:  "ACRO",
    5:  "FLY_BY_WIRE_A",
    6:  "FLY_BY_WIRE_B",
    7:  "CRUISE",
    8:  "AUTOTUNE",
    10: "AUTO",
    11: "RTL",
    12: "LOITER",
    13: "TAKEOFF",
    14: "AVOID_ADSB",
    15: "GUIDED",
    17: "QSTABILIZE",
    18: "QHOVER",
    19: "QLOITER",
    20: "QLAND",
    21: "QRTL",
    22: "QAUTOTUNE",
    23: "QACRO",
    24: "THERMAL",
}

# PX4 nav state IDs → human-readable names
PX4_NAV_STATES: dict[int, str] = {
    0:  "MANUAL",
    1:  "ALTCTL",
    2:  "POSCTL",
    3:  "AUTO_MISSION",
    4:  "AUTO_LOITER",
    5:  "AUTO_RTL",
    6:  "ACRO",
    8:  "OFFBOARD",
    9:  "STAB",
    10: "RATTITUDE",
    11: "AUTO_TAKEOFF",
    12: "AUTO_LAND",
    13: "AUTO_FOLLOW_TARGET",
    14: "AUTO_PRECLAND",
    15: "ORBIT",
    16: "AUTO_VTOL_TAKEOFF",
}


def decode_flight_mode(
    custom_mode: int,
    autopilot: int = mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
    vehicle_type: int = mavutil.mavlink.MAV_TYPE_QUADROTOR,
) -> str:
    """
    Converts a MAVLink custom_mode integer to a human-readable string.
    Falls back to 'MODE_<n>' if the mode isn't in the lookup table.
    """
    if autopilot == mavutil.mavlink.MAV_AUTOPILOT_PX4:
        return PX4_NAV_STATES.get(custom_mode, f"MODE_{custom_mode}")

    # ArduPilot — choose map based on vehicle type
    if vehicle_type in (
        mavutil.mavlink.MAV_TYPE_FIXED_WING,
        mavutil.mavlink.MAV_TYPE_VTOL_TAILSITTER_DUOROTOR,
        mavutil.mavlink.MAV_TYPE_VTOL_TAILSITTER_QUADROTOR,
        mavutil.mavlink.MAV_TYPE_VTOL_TILTROTOR,
    ):
        return ARDUPLANE_MODES.get(custom_mode, f"MODE_{custom_mode}")

    return ARDUCOPTER_MODES.get(custom_mode, f"MODE_{custom_mode}")


# ══════════════════════════════════════════════════════════════════
# GPS helpers
# ══════════════════════════════════════════════════════════════════

GPS_FIX_TYPES: dict[int, str] = {
    0: "No GPS",
    1: "No fix",
    2: "2D fix",
    3: "3D fix",
    4: "DGPS",
    5: "RTK float",
    6: "RTK fixed",
    7: "Static",
    8: "PPP",
}


def decode_gps_fix(fix_type: int) -> str:
    return GPS_FIX_TYPES.get(fix_type, f"Unknown ({fix_type})")


def gps_quality_score(fix_type: int, satellites: int, hdop: float) -> int:
    """
    Returns a 0–100 quality score for display as a signal bar.
    Used by the HUD RSSI/GPS indicator.
    """
    if fix_type < 2:
        return 0
    fix_score  = min(fix_type * 15, 50)     # up to 50 pts from fix type
    sat_score  = min(satellites * 3, 30)    # up to 30 pts from satellite count
    hdop_score = max(0, 20 - int(hdop * 4)) # up to 20 pts from HDOP (lower is better)
    return min(100, fix_score + sat_score + hdop_score)


# ══════════════════════════════════════════════════════════════════
# System status helpers
# ══════════════════════════════════════════════════════════════════

MAV_STATE_LABELS: dict[int, str] = {
    0: "UNINIT",
    1: "BOOT",
    2: "CALIBRATING",
    3: "STANDBY",
    4: "ACTIVE",
    5: "CRITICAL",
    6: "EMERGENCY",
    7: "POWEROFF",
    8: "FLIGHT_TERMINATION",
}


def decode_system_status(status_id: int) -> str:
    return MAV_STATE_LABELS.get(status_id, f"STATUS_{status_id}")


def is_armed(base_mode: int) -> bool:
    """Extract armed state from MAVLink base_mode bitmask."""
    return bool(base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)


def is_custom_mode(base_mode: int) -> bool:
    return bool(base_mode & mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED)


# ══════════════════════════════════════════════════════════════════
# Link quality helpers
# ══════════════════════════════════════════════════════════════════

def rssi_to_percent(rssi: int) -> int:
    """
    Converts raw RSSI (0–255 MAVLink scale) to 0–100%.
    Some autopilots report dBm — clamp to reasonable range.
    """
    if rssi == 255:       # 255 = unknown / not set
        return 0
    return min(100, max(0, int((rssi / 254) * 100)))


def link_quality_label(rssi_pct: int) -> str:
    if rssi_pct >= 75:
        return "Excellent"
    if rssi_pct >= 50:
        return "Good"
    if rssi_pct >= 25:
        return "Fair"
    if rssi_pct > 0:
        return "Poor"
    return "No signal"


# ══════════════════════════════════════════════════════════════════
# MAVLink command helpers
# ══════════════════════════════════════════════════════════════════

MAV_RESULT_LABELS: dict[int, str] = {
    0: "ACCEPTED",
    1: "TEMPORARILY_REJECTED",
    2: "DENIED",
    3: "UNSUPPORTED",
    4: "FAILED",
    5: "IN_PROGRESS",
    6: "CANCELLED",
}


def decode_mav_result(result: int) -> str:
    return MAV_RESULT_LABELS.get(result, f"RESULT_{result}")


def build_param_set_message(
    mav,
    param_id: str,
    value: float,
    param_type: int = mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
) -> None:
    """
    Sends a PARAM_SET message to change an autopilot parameter.
    param_id must be ≤ 16 characters (MAVLink spec).
    """
    if len(param_id) > 16:
        raise ValueError(f"param_id '{param_id}' exceeds 16-char MAVLink limit")
    mav.mav.param_set_send(
        mav.target_system,
        mav.target_component,
        param_id.encode("utf-8"),
        value,
        param_type,
    )


# ══════════════════════════════════════════════════════════════════
# Coordinate packing / unpacking
# ══════════════════════════════════════════════════════════════════

def pack_latlon(degrees: float) -> int:
    """Convert decimal degrees to MAVLink integer format (×1e7)."""
    return int(degrees * 1e7)


def unpack_latlon(mavlink_int: int) -> float:
    """Convert MAVLink integer format (×1e7) to decimal degrees."""
    return mavlink_int / 1e7


def pack_altitude(metres: float) -> int:
    """Convert metres to MAVLink millimetres format."""
    return int(metres * 1000)


def unpack_altitude(mavlink_mm: int) -> float:
    """Convert MAVLink millimetres to metres."""
    return mavlink_mm / 1000.0