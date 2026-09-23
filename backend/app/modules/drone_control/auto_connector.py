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
import time
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

# A fallback TCP/UDP candidate (tcp:host:5762, udp:14550, ...) that fails
# repeatedly with nothing listening is skipped for this long before being
# retried, instead of being re-probed every RETRY_INTERVAL forever. This
# matters specifically for TCP candidates: pymavlink's mavtcp will happily
# connect() to a port with nothing valid behind it, then spend the full
# heartbeat_timeout printing "EOF on TCP socket" on every failed read — with
# no real drone/SITL present, that repeats every 15s indefinitely and floods
# the logs. Bridge candidates (built fresh from live com_bridge status) and
# discovered serial ports are never cooled down — only the fixed fallback
# list, which is the same every cycle regardless of what's actually present.
FAILURE_COOLDOWN_S = 120
COOLDOWN_AFTER_FAILURES = 2

_candidate_failures: dict[str, int] = {}
_candidate_cooldown_until: dict[str, float] = {}


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


_FALLBACK_CANDIDATES = [
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


def _build_candidates(bridge: dict | None) -> list[dict]:
    """
    Ordered probe list.
    Bridge (cable via TCP) is always first — it is the most reliable path.
    Fallback candidates currently in their failure cooldown are skipped
    (see FAILURE_COOLDOWN_S) — bridge/serial candidates are always included
    since they're only present when something real was actually detected.
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

    now = time.monotonic()
    for c in _FALLBACK_CANDIDATES:
        if _candidate_cooldown_until.get(c["label"], 0.0) > now:
            continue
        candidates.append(c)
    return candidates


def _record_candidate_result(label: str, succeeded: bool) -> None:
    if succeeded:
        _candidate_failures.pop(label, None)
        _candidate_cooldown_until.pop(label, None)
        return
    failures = _candidate_failures.get(label, 0) + 1
    _candidate_failures[label] = failures
    if failures >= COOLDOWN_AFTER_FAILURES:
        _candidate_cooldown_until[label] = time.monotonic() + FAILURE_COOLDOWN_S
        log.debug("autoconnect.candidate_cooldown", label=label,
                  failures=failures, cooldown_s=FAILURE_COOLDOWN_S)


async def _connect_drone(drone_id: int, call_sign: str, candidates: list[dict]) -> bool:
    """
    Try every candidate concurrently and take the first one that actually
    gets a heartbeat, cancelling the rest. Candidates bind distinct ports/
    transports so probing them in parallel is safe — there's no shared
    resource to contend over. This bounds total wait to roughly one
    candidate's heartbeat_timeout instead of the sum of every candidate's
    timeout (sequential probing of N candidates could take N * timeout —
    e.g. ~40s for 5 fallback ports at 8s each — before finding the right one
    if it wasn't first in the list).

    mavlink_manager.connect() itself resolves any race between concurrent
    candidates for the same drone_id (only one can ever actually commit a
    connection; a losing candidate that got as far as a real heartbeat
    still returns False and releases its own socket) — this function just
    picks the first True result and cancels whatever's still probing.
    """
    from app.modules.drone_control.mavlink_manager import mavlink_manager

    async def _probe(c: dict) -> tuple[dict, bool]:
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
            return c, ok
        except Exception as exc:
            log.debug("autoconnect.probe_failed",
                      drone_id=drone_id, label=c["label"], error=str(exc))
            return c, False

    tasks = [asyncio.create_task(_probe(c)) for c in candidates]
    winner: dict | None = None
    try:
        pending = set(tasks)
        while pending and winner is None:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                c, ok = task.result()
                _record_candidate_result(c["label"], ok)
                if ok and winner is None:
                    winner = c
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    if winner is not None:
        log.info("autoconnect.connected",
                 drone_id=drone_id, call_sign=call_sign, via=winner["label"])
        return True

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
