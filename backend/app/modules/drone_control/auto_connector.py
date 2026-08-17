"""
Auto-Connector
==============
Background task that watches the com_bridge and auto-connects drones.

Behaviour:
  - Polls the com_bridge discovery endpoint every BRIDGE_POLL_INTERVAL seconds.
  - The moment the bridge transitions "not connected -> connected" (cable plugged in),
    triggers an IMMEDIATE connection attempt — no waiting.
  - Also retries disconnected drones every RETRY_INTERVAL seconds in case the
    first attempt failed (e.g. heartbeat timeout on cold start).
  - Never raises — any error is logged and retried on next cycle.

Timing (worst case end-to-end after cable plug-in):
  com_bridge detects serial port   ~2 s   (its own polling loop)
  auto_connector detects bridge    ~3 s   (BRIDGE_POLL_INTERVAL)
  MAVLink heartbeat wait           ~2 s   (HEARTBEAT_TIMEOUT)
  ─────────────────────────────────────
  Total                            ~7 s
"""
import asyncio
import json
import structlog
from urllib.request import urlopen

import serial.tools.list_ports
from sqlalchemy import select

log = structlog.get_logger()

BRIDGE_POLL_INTERVAL = 3     # seconds — how often we check com_bridge status
RETRY_INTERVAL       = 15    # seconds — retry cycle for unconnected drones
STARTUP_DELAY        = 5     # seconds — wait after lifespan start for DB/bridge to settle
HEARTBEAT_TIMEOUT    = 8.0   # seconds — pymavlink wait_heartbeat timeout per candidate

DISCOVERY_URL = "http://host.docker.internal:5761/ports"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_bridge_status() -> dict | None:
    """Query com_bridge discovery endpoint. Returns None if bridge not running."""
    try:
        with urlopen(DISCOVERY_URL, timeout=1.0) as r:
            return json.load(r)
    except Exception:
        return None


def _scan_linux_serial() -> list[dict]:
    """Serial devices visible inside the container (usbipd-win / native Linux)."""
    out = []
    for p in serial.tools.list_ports.comports():
        is_usb = "USB" in (p.hwid or "").upper()
        for baud in ((115200, 57600, 921600) if is_usb else (57600, 115200)):
            out.append({
                "transport":   "serial",
                "host":        "127.0.0.1",
                "port":        14550,
                "serial_port": p.device,
                "baud_rate":   baud,
                "label":       f"{p.device}@{baud}",
            })
    return out


def _build_candidates(bridge: dict | None) -> list[dict]:
    """
    Ordered probe list.
    Bridge (cable via TCP) is always first — it is the most reliable path.
    """
    candidates = []

    if bridge and bridge.get("connected"):
        tcp_port = bridge.get("tcp_port", 5762)
        baud     = bridge.get("baud", 115200)
        candidates.append({
            "transport":   "tcp",
            "host":        "host.docker.internal",
            "port":        tcp_port,
            "serial_port": "/dev/ttyUSB0",
            "baud_rate":   baud,
            "label":       f"bridge:{bridge.get('active_port')}->tcp:{tcp_port}",
        })

    candidates += _scan_linux_serial()

    candidates += [
        {"transport": "tcp", "host": "host.docker.internal", "port": 5762,
         "serial_port": "/dev/ttyUSB0", "baud_rate": 115200, "label": "tcp:host:5762"},
        {"transport": "tcp", "host": "host.docker.internal", "port": 5760,
         "serial_port": "/dev/ttyUSB0", "baud_rate": 57600,  "label": "tcp:host:5760"},
        {"transport": "udp", "host": "0.0.0.0", "port": 14550,
         "serial_port": "/dev/ttyUSB0", "baud_rate": 57600,  "label": "udp:14550"},
        {"transport": "udp", "host": "0.0.0.0", "port": 14551,
         "serial_port": "/dev/ttyUSB0", "baud_rate": 57600,  "label": "udp:14551"},
        {"transport": "udp", "host": "0.0.0.0", "port": 14560,
         "serial_port": "/dev/ttyUSB0", "baud_rate": 57600,  "label": "udp:14560"},
    ]
    return candidates


async def _connect_drone(drone_id: int, call_sign: str, candidates: list[dict]) -> bool:
    """Try each candidate in order. Returns True on first success."""
    from app.modules.drone_control.mavlink_manager import mavlink_manager

    for c in candidates:
        log.info("autoconnect.probe", drone_id=drone_id, label=c["label"])
        try:
            ok = await mavlink_manager.connect(
                drone_id      = drone_id,
                call_sign     = call_sign,
                transport     = c["transport"],
                host          = c["host"],
                port          = c["port"],
                serial_port   = c["serial_port"],
                baud_rate     = c["baud_rate"],
                heartbeat_timeout = HEARTBEAT_TIMEOUT,
            )
            if ok:
                log.info("autoconnect.connected",
                         drone_id=drone_id, call_sign=call_sign, via=c["label"])
                return True
        except Exception as exc:
            log.debug("autoconnect.probe_failed",
                      drone_id=drone_id, label=c["label"], error=str(exc))

    log.warning("autoconnect.no_heartbeat", drone_id=drone_id, tried=len(candidates))
    return False


async def _get_unconnected_drones(session_factory) -> list:
    """Return DroneInstance rows that are not currently connected."""
    from app.modules.drone_control.mavlink_manager import mavlink_manager
    from app.models.drone import DroneInstance

    async with session_factory() as db:
        # Removed and maintenance drones are not connection candidates.
        result = await db.execute(
            select(DroneInstance).where(
                DroneInstance.is_active == True,  # noqa: E712
                DroneInstance.status != "maintenance",
            )
        )
        all_drones = result.scalars().all()

    unconnected = [
        d for d in all_drones
        if not (mavlink_manager._connections.get(d.id) and
                mavlink_manager._connections[d.id].connected)
    ]
    return unconnected


# ---------------------------------------------------------------------------
# Main background task
# ---------------------------------------------------------------------------

async def run_auto_connector(session_factory) -> None:
    """
    Long-running coroutine. Start once from FastAPI lifespan as an asyncio.Task.
    Uses two independent loops:

      Bridge watcher  — polls every BRIDGE_POLL_INTERVAL seconds.
                        Fires immediately on cable-plug-in event.
      Retry loop      — every RETRY_INTERVAL seconds, reconnects any drone
                        that lost its connection.
    """
    log.info("autoconnect.started",
             bridge_poll_s=BRIDGE_POLL_INTERVAL,
             retry_s=RETRY_INTERVAL)

    await asyncio.sleep(STARTUP_DELAY)

    loop = asyncio.get_event_loop()

    # Track previous bridge state so we detect plug-in events
    prev_bridge_connected = False
    prev_bridge_port: str | None = None
    last_retry_time = 0.0

    while True:
        try:
            now = loop.time()

            # ── 1. Check bridge status ────────────────────────────
            bridge = await loop.run_in_executor(None, _get_bridge_status)

            curr_connected  = bool(bridge and bridge.get("connected"))
            curr_port: str | None = bridge.get("active_port") if bridge else None

            cable_just_plugged_in = (
                curr_connected and
                (not prev_bridge_connected or curr_port != prev_bridge_port)
            )

            if cable_just_plugged_in:
                log.info("autoconnect.cable_detected",
                         com_port=curr_port,
                         tcp_port=bridge.get("tcp_port", 5762) if bridge else None)

            # ── 2. Decide whether to attempt connections ──────────
            retry_due = (now - last_retry_time) >= RETRY_INTERVAL

            if cable_just_plugged_in or retry_due:
                unconnected = await _get_unconnected_drones(session_factory)

                if not unconnected:
                    if cable_just_plugged_in:
                        log.warning(
                            "autoconnect.no_drone_instances",
                            hint="Create a drone in Drone Master → the next cable "
                                 "plug-in will auto-connect it."
                        )
                else:
                    candidates = _build_candidates(bridge)
                    log.info("autoconnect.attempting",
                             drones=[d.call_sign for d in unconnected],
                             candidates=len(candidates),
                             trigger="cable" if cable_just_plugged_in else "retry")

                    for drone in unconnected:
                        connected = await _connect_drone(drone.id, drone.call_sign, candidates)
                        if connected:
                            from app.modules.drone_master.service import DroneInstanceService
                            async with session_factory() as db:
                                await DroneInstanceService(db).mark_used(drone.id)
                                await db.commit()

                last_retry_time = now

            prev_bridge_connected = curr_connected
            prev_bridge_port      = curr_port
        except asyncio.CancelledError:
            log.info("autoconnect.stopped")
            return
        except Exception as exc:
            log.error("autoconnect.cycle_error", error=str(exc))

        try:
            await asyncio.sleep(BRIDGE_POLL_INTERVAL)
        except asyncio.CancelledError:
            log.info("autoconnect.stopped")
            return
