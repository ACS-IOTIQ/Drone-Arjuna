import asyncio
import json
import structlog
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import serial.tools.list_ports

from app.core.rbac import require_min_role, Role
from app.database import get_db
from app.models.user import User
from app.models.mission import Mission, Waypoint
from app.models.drone import DroneInstance
from app.schemas.drone import ConnectRequest, CommandRequest, SimStartRequest, SimCommandRequest, AutoConnectRequest
from app.modules.drone_control.mavlink_manager import mavlink_manager
from app.modules.drone_control.mission_simulator import mission_simulator

log = structlog.get_logger()
router = APIRouter()
_port_executor = ThreadPoolExecutor(max_workers=1)

MISSION_PLANNER_HELP = (
    "No MAVLink heartbeat received. In Mission Planner, forward MAVLink UDP "
    "to 127.0.0.1:14550, then select Mission Planner UDP 14550 in this app."
)


# ── REST endpoints ────────────────────────────────────────────────

@router.get("/ports")
async def list_available_ports(
    _: Annotated[User, Depends(require_min_role(Role.VIEWER))],
):
    """
    Lists all serial ports and standard network endpoints
    through which a drone can connect via MAVLink.
    """
    loop = asyncio.get_event_loop()

    def _scan_serial():
        results = []
        for p in serial.tools.list_ports.comports():
            is_usb = "USB" in (p.hwid or "").upper()
            results.append({
                "port": p.device,
                "type": "usb" if is_usb else "serial",
                "desc": p.description or p.device,
                "baud": 57600,
            })
        return results

    serial_ports = await loop.run_in_executor(_port_executor, _scan_serial)

    network_ports = [
        {"port": "udp:0.0.0.0:14550", "type": "udp", "desc": "Mission Planner UDP output / MAVLink default"},
        {"port": "udp:0.0.0.0:14551", "type": "udp", "desc": "Mission Planner secondary UDP output"},
        {"port": "udp:0.0.0.0:14552", "type": "udp", "desc": "Mission Planner alternate UDP output"},
        {"port": "tcp:host.docker.internal:5760", "type": "tcp", "desc": "ArduPilot SITL TCP on Windows host"},
        {"port": "tcp:host.docker.internal:5762", "type": "tcp", "desc": "ArduPilot SITL secondary TCP on Windows host"},
        {"port": "tcp:127.0.0.1:5760", "type": "tcp", "desc": "ArduPilot SITL TCP when backend runs locally"},
        {"port": "tcp:127.0.0.1:5762", "type": "tcp", "desc": "ArduPilot SITL secondary TCP when backend runs locally"},
    ]

    return serial_ports + network_ports


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
    # Serial ports first (real hardware), then common SITL network ports
    loop = asyncio.get_event_loop()

    def _scan_serial():
        return [
            {"transport": "serial", "serial_port": p.device, "host": "127.0.0.1", "port": 14550}
            for p in serial.tools.list_ports.comports()
        ]

    serial_candidates = await loop.run_in_executor(_port_executor, _scan_serial)

    network_candidates = [
        {"transport": "udp", "host": "0.0.0.0", "port": 14550, "serial_port": "/dev/ttyUSB0"},
        {"transport": "udp", "host": "0.0.0.0", "port": 14551, "serial_port": "/dev/ttyUSB0"},
        {"transport": "udp", "host": "0.0.0.0", "port": 14552, "serial_port": "/dev/ttyUSB0"},
        {"transport": "tcp", "host": "host.docker.internal", "port": 5760, "serial_port": "/dev/ttyUSB0"},
        {"transport": "tcp", "host": "host.docker.internal", "port": 5762, "serial_port": "/dev/ttyUSB0"},
        {"transport": "tcp", "host": "127.0.0.1", "port": 5760, "serial_port": "/dev/ttyUSB0"},
        {"transport": "tcp", "host": "127.0.0.1", "port": 5762, "serial_port": "/dev/ttyUSB0"},
    ]

    candidates = serial_candidates + network_candidates

    log.info("Autoconnect starting", drone_id=drone_instance_id,
             call_sign=drone.call_sign, candidates=len(candidates))

    # ── Probe each candidate ──────────────────────────────────────
    for candidate in candidates:
        transport   = candidate["transport"]
        host        = candidate["host"]
        port        = candidate["port"]
        serial_port = candidate["serial_port"]

        log.info("Autoconnect probing", drone_id=drone_instance_id,
                 transport=transport, host=host, port=port, serial_port=serial_port)

        ok = await mavlink_manager.connect(
            drone_id=drone_instance_id,
            call_sign=drone.call_sign,
            transport=transport,
            host=host,
            port=port,
            serial_port=serial_port,
            baud_rate=57600,
            heartbeat_timeout=4.0,   # short probe timeout for auto-scan
        )

        if ok:
            log.info("Autoconnect succeeded", drone_id=drone_instance_id,
                     transport=transport, host=host, port=port, serial_port=serial_port)
            return {
                "detail":    "Connected",
                "drone_id":  drone_instance_id,
                "call_sign": drone.call_sign,
                "transport": transport,
                "host":      host if transport != "serial" else None,
                "port":      port if transport != "serial" else None,
                "serial_port": serial_port if transport == "serial" else None,
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
    connections = {c["drone_id"]: c for c in mavlink_manager.get_all_connections()}
    return {
        "drones": [
            {**state.get(did, {}), **connections.get(did, {})}
            for did in set(list(state.keys()) + list(connections.keys()))
        ]
    }


@router.post("/connect", status_code=status.HTTP_201_CREATED)
async def connect_drone(
    req: ConnectRequest,
    _: Annotated[User, Depends(require_min_role(Role.FLIGHT_CONTROLLER))],
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
    return {"detail": "Connected", "drone_id": req.drone_instance_id}


@router.post("/disconnect/{drone_id}")
async def disconnect_drone(
    drone_id: int,
    _: Annotated[User, Depends(require_min_role(Role.FLIGHT_CONTROLLER))],
):
    await mavlink_manager.disconnect(drone_id)
    return {"detail": "Disconnected"}


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
):
    """One-shot telemetry snapshot for a single drone."""
    state = mavlink_manager.state.get(drone_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Drone not connected")
    return state


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
                data = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
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
