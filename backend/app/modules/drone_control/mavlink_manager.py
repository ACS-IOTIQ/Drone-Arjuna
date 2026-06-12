"""
MAVLink Communication Manager
Manages async connections to multiple drones simultaneously.
Each drone runs in its own asyncio task reading from a UDP/TCP/serial socket.

HF transport notes:
  transport='hf_serial' — HF modem presented as a serial port (most common)
  transport='hf_tcp'    — HF modem with TCP-based ALE interface
  Both resolve to pymavlink serial/tcp connection strings; the HFLinkAdapter
  layer above handles message filtering, rate-limiting, and degraded-state logic.
"""
import asyncio
import structlog
from dataclasses import dataclass, field
from typing import Optional
from pymavlink import mavutil

from app.utils.mavlink_utils import build_connection_string
from app.modules.drone_control.telemetry_processor import TelemetryProcessor
from app.modules.drone_control.state_manager import StateManager
from app.modules.drone_control.health_monitor import HealthMonitor
from app.modules.drone_control.data_recorder import data_recorder
from app.modules.drone_control.command_controller import CommandController, CommandRecord
from app.modules.drone_control import hf_link_adapter
from app.modules.drone_control.hf_link_adapter import (
    HFLinkAdapter, HFLinkState,
    HF_HEARTBEAT_TIMEOUT_S, HF_COMMAND_ACK_TIMEOUT_S,
)

log = structlog.get_logger()

# Heartbeat wait timeout (seconds) per transport type
_HEARTBEAT_TIMEOUT: dict[str, float] = {
    "udp":       10.0,
    "tcp":       10.0,
    "serial":    10.0,
    "hf_serial": HF_HEARTBEAT_TIMEOUT_S,
    "hf_tcp":    HF_HEARTBEAT_TIMEOUT_S,
}

HF_TRANSPORTS = {"hf_serial", "hf_tcp"}


@dataclass
class DroneConnection:
    drone_id: int
    call_sign: str
    transport: str
    connection_string: str
    mav: Optional[object] = None
    task: Optional[asyncio.Task] = None
    heartbeat_task: Optional[asyncio.Task] = None
    controller: Optional[CommandController] = None
    connected: bool = False
    link_quality: int = 0
    hf_adapter: Optional[HFLinkAdapter] = None   # set when transport is HF
    errors: list[str] = field(default_factory=list)


class MAVLinkManager:
    """
    Singleton that holds all active drone connections.
    Runs one asyncio background task per drone.
    """

    def __init__(self):
        self._connections: dict[int, DroneConnection] = {}
        self._processor = TelemetryProcessor()
        self.state = StateManager()
        self._health = HealthMonitor(self)
        # Wire health monitor and data recorder into state update callbacks
        self.state.subscribe(self._health.evaluate)
        self.state.subscribe(data_recorder.record)

    def _build_connection_string(self, transport: str, host: str, port: int,
                                  serial_port: str, baud_rate: int) -> str:
        return build_connection_string(transport, host, port, serial_port, baud_rate)

    async def connect(self, drone_id: int, call_sign: str, transport: str,
                      host: str = "127.0.0.1", port: int = 14550,
                      serial_port: str = "/dev/ttyUSB0", baud_rate: int = 57600,
                      hf_modem_type: str = "generic",
                      heartbeat_timeout: float | None = None) -> bool:
        if drone_id in self._connections and self._connections[drone_id].connected:
            log.warning("Drone already connected", drone_id=drone_id)
            return True

        conn_str = self._build_connection_string(transport, host, port, serial_port, baud_rate)
        conn = DroneConnection(
            drone_id=drone_id,
            call_sign=call_sign,
            transport=transport,
            connection_string=conn_str,
        )

        # Attach HF adapter for HF transports
        if transport in HF_TRANSPORTS:
            conn.hf_adapter = hf_link_adapter.get_or_create(drone_id, hf_modem_type)
            log.info("HF link adapter attached", drone_id=drone_id, modem_type=hf_modem_type)

        heartbeat_timeout = heartbeat_timeout if heartbeat_timeout is not None else _HEARTBEAT_TIMEOUT.get(transport, 10.0)

        try:
            # pymavlink connection — runs synchronously but we offload to executor
            loop = asyncio.get_event_loop()
            conn.mav = await loop.run_in_executor(
                None,
                lambda: mavutil.mavlink_connection(conn_str, source_system=255)
            )
            # Wait for first heartbeat — HF uses a much longer timeout
            await asyncio.wait_for(
                loop.run_in_executor(None, conn.mav.wait_heartbeat),
                timeout=heartbeat_timeout,
            )

            # Request telemetry streams from ArduPilot.
            # Without this, ArduPilot only sends heartbeats — no position/attitude/etc.
            def _request_streams(mav):
                for stream_id, rate_hz in [
                    (mavutil.mavlink.MAV_DATA_STREAM_RAW_SENSORS,    2),   # GPS, IMU
                    (mavutil.mavlink.MAV_DATA_STREAM_EXTENDED_STATUS, 2),  # SYS_STATUS, battery
                    (mavutil.mavlink.MAV_DATA_STREAM_RC_CHANNELS,    2),   # RSSI
                    (mavutil.mavlink.MAV_DATA_STREAM_POSITION,       4),   # GLOBAL_POSITION_INT
                    (mavutil.mavlink.MAV_DATA_STREAM_EXTRA1,        10),   # ATTITUDE (10 Hz)
                    (mavutil.mavlink.MAV_DATA_STREAM_EXTRA2,         4),   # VFR_HUD
                    (mavutil.mavlink.MAV_DATA_STREAM_EXTRA3,         2),   # AHRS, wind
                ]:
                    mav.mav.request_data_stream_send(
                        mav.target_system,
                        mav.target_component,
                        stream_id,
                        rate_hz,
                        1,   # 1 = start streaming
                    )

            await loop.run_in_executor(None, _request_streams, conn.mav)
            log.info("Stream rates requested", drone_id=drone_id)

            conn.connected = True
            self._connections[drone_id] = conn
            self.state.init_drone(drone_id, call_sign)

            # Create a CommandController for this drone
            conn.controller = CommandController(drone_id, conn.mav, self.state)

            # Start background reader task (heartbeat is sent inside the same thread)
            conn.task = asyncio.create_task(
                self._read_loop(drone_id),
                name=f"mavlink-reader-{call_sign}"
            )
            log.info("Drone connected", drone_id=drone_id, call_sign=call_sign,
                     transport=transport)
            return True

        except asyncio.TimeoutError:
            log.error("Heartbeat timeout", drone_id=drone_id, conn_str=conn_str,
                      timeout_s=heartbeat_timeout)
            if conn.hf_adapter:
                hf_link_adapter.remove(drone_id)
            return False
        except Exception as e:
            log.error("Connection failed", drone_id=drone_id, error=str(e))
            if conn.hf_adapter:
                hf_link_adapter.remove(drone_id)
            return False

    async def disconnect(self, drone_id: int):
        conn = self._connections.get(drone_id)
        if not conn:
            return
        if conn.task:
            conn.task.cancel()
        if conn.mav:
            conn.mav.close()
        conn.connected = False
        self.state.remove_drone(drone_id)
        del self._connections[drone_id]
        hf_link_adapter.remove(drone_id)  # no-op for non-HF drones
        log.info("Drone disconnected", drone_id=drone_id)

    async def _read_loop(self, drone_id: int):
        """
        Continuous async read loop for one drone.
        Offloads blocking recv_match + heartbeat send to the same executor thread
        so the pymavlink connection object is never accessed from two threads at once.
        """
        conn = self._connections[drone_id]
        loop = asyncio.get_event_loop()
        import time as _time
        log.info("MAVLink reader started", drone_id=drone_id)
        last_hb = _time.monotonic()
        consecutive_errors = 0

        def _recv_and_heartbeat():
            nonlocal last_hb
            msg = conn.mav.recv_match(blocking=True, timeout=1.0)
            now = _time.monotonic()
            if now - last_hb >= 1.0:
                conn.mav.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0, 0, 0,
                )
                last_hb = now
            return msg

        while conn.connected:
            try:
                msg = await loop.run_in_executor(None, _recv_and_heartbeat)
                consecutive_errors = 0   # successful recv resets counter
                if msg is None:
                    continue

                # HF adapter: mark liveness and apply bandwidth filtering
                if conn.hf_adapter:
                    conn.hf_adapter.on_message_received()
                    if not conn.hf_adapter.should_forward(msg.get_type()):
                        continue

                await self._processor.process(drone_id, msg, self.state, conn.controller)

            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                log.warning("MAVLink read error", drone_id=drone_id, error=str(e),
                            consecutive=consecutive_errors)
                if consecutive_errors >= 10:
                    log.error("Connection lost — auto-disconnecting", drone_id=drone_id)
                    break
                await asyncio.sleep(0.1)

        log.info("MAVLink reader stopped", drone_id=drone_id)

        # Inline cleanup if the loop exited due to errors (not a clean cancel/disconnect)
        if drone_id in self._connections and self._connections[drone_id].connected:
            log.warning("Unclean link exit — removing stale connection", drone_id=drone_id)
            conn.connected = False
            try:
                conn.mav.close()
            except Exception:
                pass
            self.state.remove_drone(drone_id)
            self._connections.pop(drone_id, None)
            hf_link_adapter.remove(drone_id)
            log.info("Auto-disconnected", drone_id=drone_id)

    def attach_simulation(self, drone_id: int, call_sign: str):
        """Register a virtual simulation entry so the drone shows as connected."""
        conn = DroneConnection(
            drone_id=drone_id,
            call_sign=call_sign,
            transport="simulation",
            connection_string="simulation://",
            connected=True,
        )
        self._connections[drone_id] = conn
        log.info("Simulation connection registered", drone_id=drone_id)

    def detach_simulation(self, drone_id: int):
        """Remove a simulation entry (does NOT touch StateManager — simulator handles that)."""
        conn = self._connections.pop(drone_id, None)
        if conn:
            log.info("Simulation connection removed", drone_id=drone_id)

    async def send_command(self, drone_id: int, command: str, params: dict) -> CommandRecord:
        """Delegate to the drone's CommandController. Returns a CommandRecord."""
        conn = self._connections.get(drone_id)
        if not conn or not conn.connected:
            from app.modules.drone_control.command_controller import CommandResult
            rec = CommandRecord(drone_id=drone_id, command=command, params=params)
            rec.result = CommandResult.FAILED
            rec.ack_message = "Drone not connected"
            return rec

        # Route to simulator for virtual drones
        if conn.transport == "simulation":
            from app.modules.drone_control.mission_simulator import mission_simulator
            from app.modules.drone_control.command_controller import CommandResult
            await mission_simulator.command(command, params or {})
            rec = CommandRecord(drone_id=drone_id, command=command, params=params)
            rec.result = CommandResult.ACCEPTED
            return rec

        if not conn.controller:
            from app.modules.drone_control.command_controller import CommandResult
            rec = CommandRecord(drone_id=drone_id, command=command, params=params)
            rec.result = CommandResult.FAILED
            rec.ack_message = "No controller"
            return rec
        return await conn.controller.send(command, params)

    def get_command_history(self, drone_id: int, limit: int = 20) -> list:
        conn = self._connections.get(drone_id)
        if not conn or not conn.controller:
            return []
        return conn.controller.get_history(limit)

    def get_all_connections(self) -> list[dict]:
        result = []
        for c in self._connections.values():
            entry: dict = {
                "drone_id":    c.drone_id,
                "call_sign":   c.call_sign,
                "transport":   c.transport,
                "connected":   c.connected,
                "link_quality": c.link_quality,
            }
            if c.hf_adapter:
                entry["hf"] = c.hf_adapter.get_status()
            result.append(entry)
        return result


# Module-level singleton
mavlink_manager = MAVLinkManager()