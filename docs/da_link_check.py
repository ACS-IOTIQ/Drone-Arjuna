#!/usr/bin/env python3
"""
DroneArjuna link self-check (for firmware / integration engineers).

Emulates what the DroneArjuna backend does when it connects to a vehicle, so you can
prove your MAVLink output is compatible BEFORE pointing it at the production server.

  - listens on a UDP port like the backend does (pymavlink "udpin"), as GCS system id 255
  - waits for your first HEARTBEAT, then sends a 1 Hz GCS heartbeat
  - requests the same telemetry streams / message intervals the backend requests
  - collects messages for --duration seconds and reports pass / fail

Usage (run on a machine your vehicle can reach; point the vehicle's UDP output at it):
    pip install pymavlink
    python da_link_check.py --port 14550
    python da_link_check.py --port 14550 --key <64 hex chars>      # when MAVLink 2 signing is on

Exit code 0 = all required checks passed, 1 = at least one failed.
The script never sends arm / mode / takeoff commands.
"""
import argparse
import collections
import os
import sys
import time

# The DroneArjuna backend always runs pymavlink in MAVLink 2 mode (required for signing).
# pymavlink reads this at import time, so it must be set before the import below.
os.environ.setdefault("MAVLINK20", "1")

from pymavlink import mavutil  # noqa: E402

# message -> (minimum rate Hz we ask for, required?)
REQUIRED = {
    "HEARTBEAT":            (1.0, True),
    "GLOBAL_POSITION_INT":  (2.0, True),
    "ATTITUDE":             (5.0, True),
    "VFR_HUD":              (2.0, True),
    "SYS_STATUS":           (1.0, True),
    "GPS_RAW_INT":          (1.0, True),
    "RC_CHANNELS":          (1.0, False),   # used for RSSI; optional
    "BATTERY_STATUS":       (0.2, False),   # optional
}

REQUEST_RATES = {  # what the DroneArjuna backend asks for (Hz)
    "GPS_RAW_INT": 2, "RC_CHANNELS": 2, "GLOBAL_POSITION_INT": 4,
    "ATTITUDE": 10, "VFR_HUD": 4, "SYS_STATUS": 2,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=14550, help="UDP port to listen on (default 14550)")
    ap.add_argument("--key", default="", help="MAVLink 2 signing key, 64 hex chars (omit if signing is off)")
    ap.add_argument("--duration", type=float, default=20.0, help="seconds to observe after first heartbeat")
    ap.add_argument("--wait", type=float, default=60.0, help="seconds to wait for the first heartbeat")
    a = ap.parse_args()

    link = mavutil.mavlink_connection(f"udpin:0.0.0.0:{a.port}", source_system=255)
    if a.key:
        link.setup_signing(bytes.fromhex(a.key), sign_outgoing=True,
                           allow_unsigned_callback=lambda _m, mid: mid == mavutil.mavlink.MAVLINK_MSG_ID_RADIO_STATUS)
    print(f"Listening on UDP 0.0.0.0:{a.port} (signing {'ON' if a.key else 'off'}) - waiting up to {a.wait:.0f}s for a heartbeat...")

    t0 = time.monotonic()
    hb = None
    while time.monotonic() - t0 < a.wait:
        hb = link.recv_match(type="HEARTBEAT", blocking=True, timeout=1)
        if hb:
            break
    if not hb:
        print("FAIL  no HEARTBEAT received. Check destination IP/port, firewall/NAT, baud, and signing key.")
        return 1

    # Same stream requests as the backend
    for stream in (mavutil.mavlink.MAV_DATA_STREAM_RAW_SENSORS, mavutil.mavlink.MAV_DATA_STREAM_EXTENDED_STATUS,
                   mavutil.mavlink.MAV_DATA_STREAM_RC_CHANNELS, mavutil.mavlink.MAV_DATA_STREAM_POSITION,
                   mavutil.mavlink.MAV_DATA_STREAM_EXTRA1, mavutil.mavlink.MAV_DATA_STREAM_EXTRA2,
                   mavutil.mavlink.MAV_DATA_STREAM_EXTRA3):
        link.mav.request_data_stream_send(link.target_system, link.target_component, stream, 4, 1)
    for name, hz in REQUEST_RATES.items():
        link.mav.command_long_send(link.target_system, link.target_component,
                                   mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                                   getattr(mavutil.mavlink, f"MAVLINK_MSG_ID_{name}"), int(1e6 / hz), 0, 0, 0, 0, 0)

    counts = collections.Counter()
    sources = collections.Counter()            # (sysid, compid) of every HEARTBEAT
    hb_types = {}
    last = {}
    t_start = time.monotonic()
    last_gcs_hb = 0.0
    while time.monotonic() - t_start < a.duration:
        now = time.monotonic()
        if now - last_gcs_hb >= 1.0:
            link.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
            last_gcs_hb = now
        m = link.recv_match(blocking=True, timeout=1)
        if m is None:
            continue
        t = m.get_type()
        counts[t] += 1
        last[t] = m
        if t == "HEARTBEAT":
            src = (m.get_srcSystem(), m.get_srcComponent())
            sources[src] += 1
            hb_types[src] = (m.type, m.autopilot)

    elapsed = max(time.monotonic() - t_start, 1e-6)
    ok = True
    print(f"\nVehicle: system id {hb.get_srcSystem()}, component {hb.get_srcComponent()}\n")
    print(f"{'Message':22s}{'Count':>7s}{'Rate Hz':>9s}{'Need Hz':>9s}  Result")
    for name, (need, required) in REQUIRED.items():
        n = counts.get(name, 0)
        rate = n / elapsed
        good = rate >= need * 0.8
        tag = "ok" if good else ("FAIL" if required else "warn (optional)")
        ok &= good or not required
        print(f"{name:22s}{n:7d}{rate:9.2f}{need:9.1f}  {tag}")

    print()
    if len(sources) > 1:
        ok = False
        print("FAIL  more than one component sends HEARTBEAT on this link:")
        for src, n in sources.items():
            typ, ap_ = hb_types[src]
            print(f"        sys {src[0]} comp {src[1]}  type={typ} autopilot={ap_}  ({n} heartbeats)")
        print("      DroneArjuna treats every HEARTBEAT on the link as the vehicle's, so a gimbal/companion/camera\n"
              "      heartbeat overwrites flight mode and armed state. Filter other components out of this link.")
    else:
        (sysid, comp), = sources.keys()
        typ, ap_ = hb_types[(sysid, comp)]
        print(f"ok    single heartbeat source sys {sysid} comp {comp} (type={typ}, autopilot={ap_})")
        if ap_ not in (mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA, mavutil.mavlink.MAV_AUTOPILOT_PX4):
            print("warn  autopilot is not ArduPilot/PX4: flight modes will display as MODE_<n> in DroneArjuna.")

    g = last.get("GPS_RAW_INT")
    if g is not None:
        print(f"info  GPS fix_type={g.fix_type} satellites={g.satellites_visible} "
              "(DroneArjuna refuses to arm below fix 3 / 6 satellites)")
    s = last.get("SYS_STATUS")
    if s is not None:
        print(f"info  battery_remaining={s.battery_remaining}% (-1 = unknown; arm is refused below 20%)")

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
