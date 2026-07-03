import asyncio
import json
import structlog
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import serial.tools.list_ports
from urllib.request import urlopen

from app.core.rbac import require_min_role, Role
from app.database import get_db
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
                # USB-direct Pixhawk/ArduPilot connections use 115200;
                # SiK telemetry radios over a plain serial port use 57600.
                "baud": 115200 if is_usb else 57600,
            })
        return results

    serial_ports, bridge = await asyncio.gather(
        loop.run_in_executor(_port_executor, _scan_serial),
        loop.run_in_executor(_port_executor, _host_bridge_status),
    )

    if bridge and bridge.get("connected"):
        serial_ports.append({
            "port": f"tcp:host.docker.internal:{bridge.get('tcp_port', 5760)}",
            "type": "tcp",
            "desc": f"{bridge.get('active_port')} - {bridge.get('description')} (Windows COM bridge)",
            "baud": bridge.get("baud"),
        })

    network_ports = [
        {"port": "tcp:host.docker.internal:5760", "type": "tcp", "desc": "Windows hardware COM bridge"},
        {"port": "udp:0.0.0.0:14550",   "type": "udp", "desc": "MAVLink UDP (SITL / GCS default)"},
        {"port": "udp:0.0.0.0:14551",   "type": "udp", "desc": "MAVLink UDP (secondary GCS)"},
        {"port": "tcp:127.0.0.1:5760",  "type": "tcp", "desc": "MAVLink TCP (SITL ArduPilot default)"},
        {"port": "tcp:127.0.0.1:5762",  "type": "tcp", "desc": "MAVLink TCP (SITL secondary)"},
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

    network_candidates = [
        {"transport": "tcp", "host": "host.docker.internal", "port": 5760, "serial_port": "/dev/ttyUSB0", "baud_rate": 57600},
        {"transport": "udp", "host": "0.0.0.0",     "port": 14550, "serial_port": "/dev/ttyUSB0", "baud_rate": 57600},
        {"transport": "udp", "host": "0.0.0.0",     "port": 14551, "serial_port": "/dev/ttyUSB0", "baud_rate": 57600},
        {"transport": "tcp", "host": "127.0.0.1",   "port": 5760,  "serial_port": "/dev/ttyUSB0", "baud_rate": 57600},
    ]

    if bridge and bridge.get("connected"):
        network_candidates = [
            {
                "transport": "tcp",
                "host": "host.docker.internal",
                "port": bridge.get("tcp_port", 5760),
                "serial_port": "/dev/ttyUSB0",
                "baud_rate": bridge.get("baud", 115200),
            }
        ] + network_candidates

    candidates = serial_candidates + network_candidates

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
    """Start a simulated flight of a saved mission."""
    if mission_simulator.active:
        raise HTTPException(status_code=409, detail="A simulation is already running")

    # Fetch mission
    mission = await db.get(Mission, req.mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    # Resolve drone instance
    drone_id = req.drone_instance_id or mission.drone_instance_id
    if not drone_id:
        raise HTTPException(status_code=422, detail="No drone assigned — set drone_instance_id")
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

    # Home position = first waypoint's lat/lon (ground level)
    home_lat = float(wps[0].latitude)
    home_lon = float(wps[0].longitude)

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

    # Start the simulator (injects into the same StateManager)
    await mission_simulator.start(
        drone_id=drone_id,
        call_sign=drone.call_sign,
        waypoints=waypoint_dicts,
        home_lat=home_lat,
        home_lon=home_lon,
        speed_mult=req.speed_multiplier,
        state_mgr=mavlink_manager.state,
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
):
    if not mission_simulator.active:
        raise HTTPException(status_code=404, detail="No simulation running")
    drone_id = mission_simulator.drone_id
    await mission_simulator.stop()
    if drone_id is not None:
        mavlink_manager.detach_simulation(drone_id)
    return {"detail": "Simulation stopped"}


@router.get("/simulate/status")
async def simulation_status(
    _: Annotated[User, Depends(require_min_role(Role.VIEWER))],
):
    return mission_simulator.get_status()


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
