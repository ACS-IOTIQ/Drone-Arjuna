import asyncio
import json
import structlog
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
import serial.tools.list_ports
from urllib.request import urlopen

from app.core.rbac import require_min_role, Role
from app.database import get_db, get_ts_db
from app.models.user import User
from app.models.mission import Mission, Waypoint
from app.models.drone import DroneInstance
from app.schemas.drone import ConnectRequest, CommandRequest, SimStartRequest, SimCommandRequest, AutoConnectRequest, GeofenceSetRequest
from app.utils.geofence import geofence_store
from app.modules.drone_control.mavlink_manager import mavlink_manager
from app.modules.drone_control.mission_simulator import mission_simulator

log = structlog.get_logger()
router = APIRouter()
_port_executor = ThreadPoolExecutor(max_workers=1)

MISSION_PLANNER_HELP = (
    "No MAVLink heartbeat received. In Mission Planner, forward MAVLink UDP "
    "to 127.0.0.1:14550, then select Mission Planner UDP 14550 in this app."
)


def _host_bridge_status() -> dict | None:
    """Return COM bridge status from the com-bridge Docker service."""
    try:
        with urlopen("http://host.docker.internal:5761/ports", timeout=0.5) as response:
            return json.load(response)
    except Exception:
        return None


# ── REST endpoints ────────────────────────────────────────────────

@router.get("/ports")
async def list_available_ports(
    _: Annotated[User, Depends(require_min_role(Role.VIEWER))],
):
    """
    Lists all connectable ports: Windows COM ports (via com_bridge),
    Linux serial devices inside the container, and standard MAVLink
    network endpoints.

    Windows COM ports are discovered by querying the com_bridge discovery
    HTTP endpoint on the host (port 5761).  Each Windows COM port is exposed
    as a TCP connection through the bridge regardless of whether the bridge
    currently has that port open.
    """
    loop = asyncio.get_event_loop()

    def _scan_serial():
        """Scan Linux serial devices visible inside the container."""
        results = []
        for p in serial.tools.list_ports.comports():
            is_usb = "USB" in (p.hwid or "").upper()
            results.append({
                "port":   p.device,
                "type":   "usb" if is_usb else "serial",
                "desc":   p.description or p.device,
                "baud":   115200 if is_usb else 57600,
                "source": "container",
            })
        return results

    serial_ports, bridge = await asyncio.gather(
        loop.run_in_executor(_port_executor, _scan_serial),
        loop.run_in_executor(_port_executor, _host_bridge_status),
    )

    # --- Windows COM ports from com_bridge -----------------------------------
    # bridge["ports"] contains every COM port visible on the Windows host.
    # bridge["active_port"] is the one the bridge currently has open.
    # We surface all of them; the active one is marked ready=True and gets
    # the live tcp_port; inactive ones advertise the default bridge TCP port.
    windows_ports = []
    if bridge:
        active    = bridge.get("active_port")        # e.g. "COM4"
        tcp_port  = bridge.get("tcp_port", 5762)
        baud      = bridge.get("baud", 115200)
        bridge_connected = bridge.get("connected", False)

        for wp in bridge.get("ports", []):
            com = wp.get("port", "")
            desc = wp.get("desc", com)
            hwid = wp.get("hwid", "")
            is_active = (com == active and bridge_connected)
            is_usb = "USB" in hwid.upper()

            windows_ports.append({
                "port":   f"tcp:host.docker.internal:{tcp_port}",
                "type":   "tcp",
                "desc":   f"{com} - {desc} (Windows bridge{' - READY' if is_active else ''})",
                "baud":   baud if is_active else (115200 if is_usb else 57600),
                "source": "windows_bridge",
                "com":    com,
                "ready":  is_active,
            })

        # If the bridge is connected but its active port wasn't in the ports
        # list (edge case), add it explicitly.
        if bridge_connected and active and not any(
            wp["com"] == active for wp in windows_ports
        ):
            windows_ports.append({
                "port":   f"tcp:host.docker.internal:{tcp_port}",
                "type":   "tcp",
                "desc":   f"{active} - {bridge.get('description', active)} (Windows bridge - READY)",
                "baud":   baud,
                "source": "windows_bridge",
                "com":    active,
                "ready":  True,
            })

    network_ports = [
        {"port": "udp:0.0.0.0:14550",  "type": "udp",  "source": "network",
         "desc": "MAVLink UDP inbound  (SITL / telemetry radio default)", "baud": None},
        {"port": "udp:0.0.0.0:14551",  "type": "udp",  "source": "network",
         "desc": "MAVLink UDP inbound  (secondary GCS port)",             "baud": None},
        {"port": "udp:0.0.0.0:14552",  "type": "udp",  "source": "network",
         "desc": "MAVLink UDP inbound  (alternate GCS port)",             "baud": None},
        {"port": "tcp:host.docker.internal:5762", "type": "tcp", "source": "network",
         "desc": "Windows hardware COM bridge (TCP 5762)",                "baud": None},
        {"port": "tcp:host.docker.internal:5760", "type": "tcp", "source": "network",
         "desc": "Windows hardware COM bridge legacy (TCP 5760)",         "baud": None},
        {"port": "tcp:127.0.0.1:5760", "type": "tcp",  "source": "network",
         "desc": "MAVLink TCP - ArduPilot SITL default",                  "baud": None},
        {"port": "tcp:127.0.0.1:5762", "type": "tcp",  "source": "network",
         "desc": "MAVLink TCP - ArduPilot SITL secondary (local backend)", "baud": None},
    ]

    return {
        "bridge_connected": bool(bridge and bridge.get("connected")),
        "bridge_active_port": bridge.get("active_port") if bridge else None,
        "ports": windows_ports + serial_ports + network_ports,
    }


async def _apply_ui_home_on_connect(drone_id: int, db: AsyncSession):
    """
    After a fresh MAVLink connection, push whatever home point the UI has
    configured (the home waypoint of this drone's most recently created
    mission) straight to the vehicle via MAV_CMD_DO_SET_HOME — so RTL/home
    matches the map immediately, without needing a manual "Set Home Here"
    in an external GCS.
    """
    result = await db.execute(
        select(Waypoint)
        .join(Mission, Mission.id == Waypoint.mission_id)
        .where(Mission.drone_instance_id == drone_id, Waypoint.is_home == True)  # noqa: E712
        .order_by(Mission.created_at.desc())
        .limit(1)
    )
    home_wp = result.scalar_one_or_none()
    if not home_wp:
        return
    ok = await mavlink_manager.send_set_home(drone_id, home_wp.latitude, home_wp.longitude)
    if ok:
        log.info("UI home location pushed to drone on connect", drone_id=drone_id,
                 lat=home_wp.latitude, lon=home_wp.longitude)


@router.post("/autoconnect", status_code=status.HTTP_200_OK)
async def autoconnect_drone(
    req: AutoConnectRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_min_role(Role.FLIGHT_CONTROLLER)),
):
    """
    Tries every available serial port then common MAVLink UDP/TCP ports in order.
    Connects on the first port that returns a heartbeat within 4 seconds.
    Returns 200 with connection details on success, 503 if all ports fail.
    """
    drone_instance_id: int = req.drone_instance_id

    drone = await db.get(DroneInstance, drone_instance_id)
    if not drone:
        raise HTTPException(status_code=404, detail=f"Drone instance #{drone_instance_id} not found")

    if mavlink_manager._connections.get(drone_instance_id, None) and \
       mavlink_manager._connections[drone_instance_id].connected:
        raise HTTPException(status_code=409, detail="Drone is already connected")

    # ── Build candidate list ──────────────────────────────────────
    # Serial ports first (real hardware), then common SITL network ports.
    # USB-direct Pixhawk/ArduPilot connections (e.g. via USB cable) always
    # speak at 115200 baud regardless of the SERIALx param — that's the
    # rate Mission Planner/QGroundControl use for the USB CDC-ACM port.
    # SiK telemetry radios (plain "serial" hwid, no USB) use 57600.
    # We try both, USB-appropriate rate first, so real hardware over a
    # cable is found without requiring any external GCS.
    loop = asyncio.get_event_loop()

    def _scan_serial():
        candidates = []
        for p in serial.tools.list_ports.comports():
            is_usb = "USB" in (p.hwid or "").upper()
            bauds = (115200, 57600, 921600) if is_usb else (57600, 115200)
            for baud in bauds:
                candidates.append({
                    "transport": "serial",
                    "serial_port": p.device,
                    "host": "127.0.0.1",
                    "port": 14550,
                    "baud_rate": baud,
                })
        return candidates

    serial_candidates, bridge = await asyncio.gather(
        loop.run_in_executor(_port_executor, _scan_serial),
        loop.run_in_executor(_port_executor, _host_bridge_status),
    )

    # If com_bridge is running and has a port open, put it FIRST — it is the
    # most reliable path for a cable-connected drone on Windows Docker.
    bridge_candidates = []
    if bridge and bridge.get("connected"):
        bridge_candidates.append({
            "transport":   "tcp",
            "host":        "host.docker.internal",
            "port":        bridge.get("tcp_port", 5762),
            "serial_port": "/dev/ttyUSB0",
            "baud_rate":   bridge.get("baud", 115200),
        })
        log.info("Autoconnect: bridge ready",
                 com_port=bridge.get("active_port"),
                 tcp_port=bridge.get("tcp_port", 5762))

    network_candidates = [
        {"transport": "tcp", "host": "host.docker.internal", "port": 5762,  "serial_port": "/dev/ttyUSB0", "baud_rate": 115200},
        {"transport": "tcp", "host": "host.docker.internal", "port": 5760,  "serial_port": "/dev/ttyUSB0", "baud_rate": 57600},
        {"transport": "udp", "host": "0.0.0.0",              "port": 14550, "serial_port": "/dev/ttyUSB0", "baud_rate": 57600},
        {"transport": "udp", "host": "0.0.0.0",              "port": 14551, "serial_port": "/dev/ttyUSB0", "baud_rate": 57600},
        {"transport": "udp", "host": "0.0.0.0",              "port": 14552, "serial_port": "/dev/ttyUSB0", "baud_rate": 57600},
        {"transport": "tcp", "host": "127.0.0.1",            "port": 5760,  "serial_port": "/dev/ttyUSB0", "baud_rate": 57600},
        {"transport": "tcp", "host": "127.0.0.1",            "port": 5762,  "serial_port": "/dev/ttyUSB0", "baud_rate": 57600},
    ]

    # Order: bridge (ready, cable) → Linux serial → network fallbacks
    candidates = bridge_candidates + serial_candidates + network_candidates

    log.info("Autoconnect starting", drone_id=drone_instance_id,
             call_sign=drone.call_sign, candidates=len(candidates))

    # ── Probe each candidate ──────────────────────────────────────
    for candidate in candidates:
        transport   = candidate["transport"]
        host        = candidate["host"]
        port        = candidate["port"]
        serial_port = candidate["serial_port"]
        baud_rate   = candidate.get("baud_rate", 57600)

        log.info("Autoconnect probing", drone_id=drone_instance_id,
                 transport=transport, host=host, port=port,
                 serial_port=serial_port, baud_rate=baud_rate)

        ok = await mavlink_manager.connect(
            drone_id=drone_instance_id,
            call_sign=drone.call_sign,
            transport=transport,
            host=host,
            port=port,
            serial_port=serial_port,
            baud_rate=baud_rate,
            heartbeat_timeout=6.0,   # real hardware may take a moment after cable plug-in
        )

        if ok:
            log.info("Autoconnect succeeded", drone_id=drone_instance_id,
                     transport=transport, host=host, port=port,
                     serial_port=serial_port, baud_rate=baud_rate)
            await _apply_ui_home_on_connect(drone_instance_id, db)
            return {
                "detail":    "Connected",
                "drone_id":  drone_instance_id,
                "call_sign": drone.call_sign,
                "transport": transport,
                "host":      host if transport != "serial" else None,
                "port":      port if transport != "serial" else None,
                "serial_port": serial_port if transport == "serial" else None,
                "baud_rate": baud_rate if transport == "serial" else None,
            }

    log.warning("Autoconnect exhausted all candidates", drone_id=drone_instance_id)
    raise HTTPException(
        status_code=503,
        detail=f"Autoconnect failed — no heartbeat received on any of the "
               f"{len(candidates)} candidate port(s). "
               f"Ensure the drone or SITL is running and reachable."
    )


@router.get("/status")
async def get_fleet_status(
    _: Annotated[User, Depends(require_min_role(Role.VIEWER))]
):
    """All connected drones + their current telemetry snapshot."""
    state = mavlink_manager.state.get_all()
    connections = {
        c["drone_id"]: c
        for c in mavlink_manager.get_all_connections()
        if c.get("connected")
    }
    return {
        "drones": [
            {**state.get(did, {}), **connections.get(did, {})}
            for did in connections.keys()
        ]
    }


async def _require_live_drone(drone_id: int, db: AsyncSession):
    drone = await db.get(DroneInstance, drone_id)
    if not drone:
        raise HTTPException(status_code=404, detail="Drone not found")

    conn = mavlink_manager._connections.get(drone_id)
    if not conn or not conn.connected:
        raise HTTPException(status_code=404, detail="Drone not connected")

    state = mavlink_manager.state.get(drone_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Drone telemetry not available")
    return state


@router.post("/connect", status_code=status.HTTP_201_CREATED)
async def connect_drone(
    req: ConnectRequest,
    _: Annotated[User, Depends(require_min_role(Role.FLIGHT_CONTROLLER))],
    db: AsyncSession = Depends(get_db),
):
    """Establish MAVLink connection to a drone."""
    ok = await mavlink_manager.connect(
        drone_id=req.drone_instance_id,
        call_sign=f"DRONE-{req.drone_instance_id}",
        transport=req.transport,
        host=req.host or "127.0.0.1",
        port=req.port or 14550,
        serial_port=req.serial_port or "/dev/ttyUSB0",
        baud_rate=req.baud_rate,
        hf_modem_type=req.hf_modem_type,
    )
    if not ok:
        raise HTTPException(status_code=503, detail="Connection failed or heartbeat timed out")
    await _apply_ui_home_on_connect(req.drone_instance_id, db)
    return {"detail": "Connected", "drone_id": req.drone_instance_id}


@router.post("/disconnect/{drone_id}")
async def disconnect_drone(
    drone_id: int,
    _: Annotated[User, Depends(require_min_role(Role.FLIGHT_CONTROLLER))],
):
    await mavlink_manager.disconnect(drone_id)
    return {"detail": "Disconnected"}


@router.get("/drones/{drone_id}/geofence")
async def get_drone_geofence(
    drone_id: int,
    _: Annotated[User, Depends(require_min_role(Role.VIEWER))],
):
    """Return the currently active runtime geofence for a drone, if any."""
    fence = geofence_store.get_geofence(drone_id)
    return {"drone_id": drone_id, "geofence": fence}


@router.post("/drones/{drone_id}/geofence", status_code=200)
async def set_drone_geofence(
    drone_id: int,
    body: GeofenceSetRequest,
    _: Annotated[User, Depends(require_min_role(Role.FLIGHT_CONTROLLER))],
):
    """
    Register or clear a runtime geofence for a connected drone.
    On breach the TelemetryProcessor automatically dispatches RTL.
    Pass geofence: null to clear.
    """
    ok = geofence_store.set_geofence(drone_id, body.geofence)
    if not ok:
        raise HTTPException(status_code=422, detail="Invalid GeoJSON geometry — must be Polygon or MultiPolygon")
    if body.geofence is None:
        return {"detail": "Geofence cleared", "drone_id": drone_id}
    return {"detail": "Geofence set", "drone_id": drone_id, "active": True}


@router.post("/command")
async def send_command(
    req: CommandRequest,
    _: Annotated[User, Depends(require_min_role(Role.FLIGHT_CONTROLLER))],
):
    """
    Send a flight command. Commands that affect safety (arm, disarm, rtl)
    are restricted to FLIGHT_CONTROLLER and above.
    """
    from app.modules.drone_control.command_controller import CommandResult
    rec = await mavlink_manager.send_command(req.drone_id, req.command, req.params)
    if rec.result == CommandResult.FAILED:
        raise HTTPException(
            status_code=503,
            detail=rec.ack_message or "Command failed — drone not connected",
        )
    return {"detail": f"Command '{req.command}' sent", "drone_id": req.drone_id}


@router.get("/telemetry/{drone_id}")
async def get_telemetry(
    drone_id: int,
    _: Annotated[User, Depends(require_min_role(Role.VIEWER))],
    db: AsyncSession = Depends(get_db),
):
    """One-shot telemetry snapshot for a single drone."""
    return await _require_live_drone(drone_id, db)


@router.get("/telemetry/{drone_id}/gauges")
async def get_telemetry_gauges(
    drone_id: int,
    _: Annotated[User, Depends(require_min_role(Role.VIEWER))],
    main_db: AsyncSession = Depends(get_db),
    db: AsyncSession = Depends(get_ts_db),
):
    """
    Current gauge telemetry (Battery, Altitude, GND Speed, GPS Sats,
    RSSI, CPU Load) for a drone — one row per drone_id, no history retained.
    """
    await _require_live_drone(drone_id, main_db)
    result = await db.execute(
        text("""
            SELECT recorded_at, battery_pct, altitude_m, ground_speed_ms,
                   gps_satellites, rssi, cpu_load_pct
            FROM telemetry_gauges
            WHERE drone_id = :drone_id
        """),
        {"drone_id": drone_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="No gauge data recorded for this drone")
    return {
        "recorded_at": row["recorded_at"],
        "battery_remaining_pct": row["battery_pct"],
        "alt_agl": row["altitude_m"],
        "groundspeed_ms": row["ground_speed_ms"],
        "gps_satellites": row["gps_satellites"],
        "rssi": row["rssi"],
        "cpu_load_pct": row["cpu_load_pct"],
    }


@router.get("/telemetry/{drone_id}/history")
async def get_telemetry_history(
    drone_id: int,
    _: Annotated[User, Depends(require_min_role(Role.VIEWER))],
    db: AsyncSession = Depends(get_ts_db),
    start: datetime | None = None,
    end: datetime | None = None,
):
    """
    Flight-path history for the Telemetry Replay Player, oldest first.

    Reads `telemetry_history` — a narrow, append-only table retained for
    1 day (see RETENTION_DAYS in data_recorder.py), separate from the
    single-row-per-drone `telemetry`/`telemetry_gauges` tables used for
    live/current state.

    `start`/`end` default to the last hour if omitted.
    """
    end = end or datetime.now(timezone.utc)
    start = start or (end - timedelta(hours=1))
    result = await db.execute(
        text("""
            SELECT recorded_at, lat, lon, alt_agl, yaw_deg, pitch_deg, roll_deg
            FROM telemetry_history
            WHERE drone_id = :drone_id AND recorded_at BETWEEN :start AND :end
            ORDER BY recorded_at ASC
        """),
        {"drone_id": drone_id, "start": start, "end": end},
    )
    return [
        {
            "timestamp": r["recorded_at"],
            "lat":   r["lat"],
            "lng":   r["lon"],
            "alt":   r["alt_agl"],
            "yaw":   r["yaw_deg"],
            "pitch": r["pitch_deg"],
            "roll":  r["roll_deg"],
        }
        for r in result.mappings().all()
    ]


# ── Mission simulation ────────────────────────────────────────────

@router.post("/simulate/start", status_code=status.HTTP_201_CREATED)
async def start_simulation(
    req: SimStartRequest,
    _: Annotated[User, Depends(require_min_role(Role.FLIGHT_CONTROLLER))],
    db: AsyncSession = Depends(get_db),
):
    """Start a simulated flight of a saved mission. Multiple drones may fly concurrently."""
    # Fetch mission
    mission = await db.get(Mission, req.mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    # Resolve drone instance
    drone_id = req.drone_instance_id or mission.drone_instance_id
    if not drone_id:
        raise HTTPException(status_code=422, detail="No drone assigned — set drone_instance_id")

    if mission_simulator.is_active(drone_id):
        raise HTTPException(status_code=409, detail=f"Drone #{drone_id} already has an active simulation")

    drone = await db.get(DroneInstance, drone_id)
    if not drone:
        raise HTTPException(status_code=404, detail="Drone instance not found")

    # Fetch waypoints ordered by sequence, skip home waypoints
    result = await db.execute(
        select(Waypoint)
        .where(Waypoint.mission_id == req.mission_id, Waypoint.is_home == False)  # noqa: E712
        .order_by(Waypoint.sequence)
    )
    wps = result.scalars().all()
    if not wps:
        raise HTTPException(status_code=422, detail="Mission has no waypoints")

    # Home position = the mission's actual home waypoint (is_home=True),
    # i.e. wherever the drone actually launches from — NOT wps[0], which is
    # the first *flight* waypoint since home waypoints are excluded above.
    # Falls back to the first flight waypoint only if no home was recorded.
    home_result = await db.execute(
        select(Waypoint)
        .where(Waypoint.mission_id == req.mission_id, Waypoint.is_home == True)  # noqa: E712
        .order_by(Waypoint.sequence)
        .limit(1)
    )
    home_wp = home_result.scalar_one_or_none()
    home_lat = float(home_wp.latitude) if home_wp else float(wps[0].latitude)
    home_lon = float(home_wp.longitude) if home_wp else float(wps[0].longitude)

    waypoint_dicts = [
        {
            "sequence":    w.sequence,
            "latitude":    w.latitude,
            "longitude":   w.longitude,
            "altitude_m":  w.altitude_m,
            "altitude_ref": w.altitude_ref,
            "speed_ms":    w.speed_ms,
            "action":      w.action,
            "loiter_time_s": w.loiter_time_s,
        }
        for w in wps
    ]

    # Register virtual connection in mavlink_manager so the drone appears "connected"
    mavlink_manager.attach_simulation(drone_id, drone.call_sign)

    # Arm runtime geofence so breach detection fires during simulation
    if mission.geofence:
        geofence_store.set_geofence(drone_id, mission.geofence)

    # Start the simulator (injects into the same StateManager, and MAVLink
    # UDP-broadcasts so external GCS software like Mission Planner sees it too)
    await mission_simulator.start(
        drone_id=drone_id,
        call_sign=drone.call_sign,
        waypoints=waypoint_dicts,
        home_lat=home_lat,
        home_lon=home_lon,
        speed_mult=req.speed_multiplier,
        state_mgr=mavlink_manager.state,
        mavlink_system_id=drone.mavlink_system_id,
    )

    return {
        "detail": "Simulation started",
        "drone_id": drone_id,
        "call_sign": drone.call_sign,
        "waypoint_count": len(waypoint_dicts),
        "speed_multiplier": req.speed_multiplier,
    }


@router.delete("/simulate/stop")
async def stop_simulation(
    _: Annotated[User, Depends(require_min_role(Role.FLIGHT_CONTROLLER))],
    drone_id: Optional[int] = None,
):
    """Stop one drone's simulation (?drone_id=N), or all running simulations if omitted."""
    if drone_id is not None:
        if not mission_simulator.is_active(drone_id):
            raise HTTPException(status_code=404, detail=f"No active simulation for drone #{drone_id}")
        await mission_simulator.stop(drone_id)
        mavlink_manager.detach_simulation(drone_id)
        return {"detail": "Simulation stopped", "drone_id": drone_id}

    active_ids = mission_simulator.active_drone_ids()
    if not active_ids:
        raise HTTPException(status_code=404, detail="No simulation running")
    for did in active_ids:
        await mission_simulator.stop(did)
        mavlink_manager.detach_simulation(did)
    return {"detail": "Simulations stopped", "drone_ids": active_ids}


@router.get("/simulate/status")
async def simulation_status(
    _: Annotated[User, Depends(require_min_role(Role.VIEWER))],
    drone_id: Optional[int] = None,
):
    """One drone's status (?drone_id=N), or {"simulations": [...]} for all active flights."""
    if drone_id is not None:
        status_dict = mission_simulator.get_status(drone_id)
        return status_dict or {
            "active": False, "phase": "idle", "drone_id": drone_id, "call_sign": "",
            "waypoint_index": 0, "waypoint_count": 0, "progress": 0.0, "speed_multiplier": 1.0,
        }
    return {"simulations": mission_simulator.get_status()}


# ── WebSocket telemetry stream ────────────────────────────────────

class ConnectionManager:
    """
    Manages telemetry subscribers via per-connection asyncio Queues.
    broadcast() is non-blocking — it puts frames into each subscriber's queue.
    The WebSocket sender task drains the queue, ensuring only one coroutine
    ever calls ws.send_text() per connection (no concurrent-send crashes).
    """

    def __init__(self):
        self._queues: dict[int, list[asyncio.Queue]] = {}

    def subscribe(self, drone_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=60)   # ~6 s buffer at 10 Hz
        self._queues.setdefault(drone_id, []).append(q)
        return q

    def unsubscribe(self, drone_id: int, q: asyncio.Queue):
        lst = self._queues.get(drone_id, [])
        if q in lst:
            lst.remove(q)

    async def broadcast(self, drone_id: int, state: dict):
        text = json.dumps(state, default=str)
        for q in list(self._queues.get(drone_id, [])):
            try:
                q.put_nowait(text)
            except asyncio.QueueFull:
                pass   # slow consumer — drop frame rather than block


ws_manager = ConnectionManager()

# Wire state manager → WebSocket broadcaster once at module load
async def _on_state_update(drone_id: int, state: dict):
    await ws_manager.broadcast(drone_id, state)

mavlink_manager.state.subscribe(_on_state_update)


@router.websocket("/stream/{drone_id}")
async def telemetry_stream(drone_id: int, ws: WebSocket):
    """
    WebSocket endpoint: WS /api/drone-control/stream/{drone_id}
    Uses a producer/consumer queue so only the sender task ever calls
    ws.send_text(), avoiding concurrent-send crashes in Starlette.
    """
    await ws.accept()
    queue = ws_manager.subscribe(drone_id)

    # Seed with current state so the client gets data immediately
    state = mavlink_manager.state.get(drone_id)
    if state:
        try:
            queue.put_nowait(json.dumps(state, default=str))
        except asyncio.QueueFull:
            pass

    async def _sender():
        """Drains the queue and writes frames to the WebSocket."""
        try:
            while True:
                text = await queue.get()
                await ws.send_text(text)
        except Exception:
            pass

    async def _receiver():
        """Reads client pings and enqueues pong replies."""
        try:
            while True:
                data = await asyncio.wait_for(ws.receive_text(), timeout=60.0)
                if data and json.loads(data).get("type") == "ping":
                    queue.put_nowait('{"type":"pong"}')
        except (WebSocketDisconnect, asyncio.TimeoutError, Exception):
            pass

    sender_task   = asyncio.create_task(_sender())
    receiver_task = asyncio.create_task(_receiver())

    # Run until either side disconnects
    await asyncio.wait({sender_task, receiver_task},
                       return_when=asyncio.FIRST_COMPLETED)

    sender_task.cancel()
    receiver_task.cancel()
    ws_manager.unsubscribe(drone_id, queue)
    log.info("WebSocket disconnected", drone_id=drone_id)
