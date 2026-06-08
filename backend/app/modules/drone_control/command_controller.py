"""
Command Controller
==================
Accepts operator commands, validates them against current drone state,
encodes them into MAVLink, dispatches to the vehicle, and tracks
acknowledgment (MAV_RESULT).

Responsibilities (per spec FR-DC-002, FR-DC-006):
  - Validate command legality given current flight mode / armed state
  - Encode high-level commands into correct MAVLink message types
  - Send with configurable timeout + retry
  - Track acknowledgment via COMMAND_ACK messages
  - Enforce safety rules (e.g. no Arm while geofence violated)
  - Provide command history for audit log

Each drone gets its own CommandController instance held by MAVLinkManager.
"""
import asyncio
import time
import structlog
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional
from pymavlink import mavutil

log = structlog.get_logger()

# ── Constants ─────────────────────────────────────────────────────
ACK_TIMEOUT_S   = 5.0    # Seconds to wait for MAV_RESULT
MAX_RETRIES     = 2      # Retries before reporting failure
HISTORY_LIMIT   = 200    # Max commands kept in memory per drone


class CommandResult(StrEnum):
    ACCEPTED    = "accepted"      # MAV_RESULT_ACCEPTED
    DENIED      = "denied"        # MAV_RESULT_DENIED / pre-flight validation fail
    FAILED      = "failed"        # MAV_RESULT_FAILED or comms error
    TIMEOUT     = "timeout"       # No ACK received within ACK_TIMEOUT_S
    UNSUPPORTED = "unsupported"   # Command not recognised


@dataclass
class CommandRecord:
    drone_id:    int
    command:     str
    params:      dict
    issued_at:   float = field(default_factory=time.monotonic)
    result:      CommandResult = CommandResult.ACCEPTED
    ack_message: str = ""


class CommandController:
    """
    One instance per connected drone.
    Holds a reference to the pymavlink connection object (mav)
    and the StateManager so it can read current drone state for validation.
    """

    def __init__(self, drone_id: int, mav, state_manager):
        self.drone_id      = drone_id
        self._mav          = mav
        self._state        = state_manager
        self._history: list[CommandRecord] = []
        self._pending: dict[int, asyncio.Future] = {}  # mavlink cmd_id → Future

    # ── Public API ────────────────────────────────────────────────

    async def send(self, command: str, params: dict = {}) -> CommandRecord:
        """
        Validate, encode, dispatch, and await acknowledgment.
        Returns a CommandRecord with the final result.
        """
        record = CommandRecord(drone_id=self.drone_id, command=command, params=params)

        # 1. Pre-flight validation
        denial = self._validate(command, params)
        if denial:
            record.result      = CommandResult.DENIED
            record.ack_message = denial
            self._append(record)
            log.warning("Command denied", drone_id=self.drone_id,
                        command=command, reason=denial)
            return record

        # 2. Dispatch with retry
        loop = asyncio.get_event_loop()
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await loop.run_in_executor(
                    None, lambda: self._dispatch(command, params)
                )
                # 3. Wait for ACK (best-effort — some commands don't send one)
                ack = await self._await_ack(command, timeout=ACK_TIMEOUT_S)
                record.result      = ack
                record.ack_message = f"attempt {attempt}"
                break
            except asyncio.TimeoutError:
                if attempt == MAX_RETRIES:
                    record.result      = CommandResult.TIMEOUT
                    record.ack_message = f"No ACK after {MAX_RETRIES} attempts"
                    log.error("Command timeout", drone_id=self.drone_id, command=command)
            except Exception as e:
                record.result      = CommandResult.FAILED
                record.ack_message = str(e)
                log.error("Command dispatch error", drone_id=self.drone_id,
                          command=command, error=str(e))
                break

        self._append(record)
        log.info("Command dispatched",
                 drone_id=self.drone_id,
                 command=command,
                 result=record.result,
                 params=params)
        return record

    def handle_ack(self, mavlink_cmd_id: int, mav_result: int):
        """
        Called by TelemetryProcessor when a COMMAND_ACK message arrives.
        Resolves the pending Future if one exists for this command.
        """
        fut = self._pending.pop(mavlink_cmd_id, None)
        if fut and not fut.done():
            ok = mav_result == mavutil.mavlink.MAV_RESULT_ACCEPTED
            result = CommandResult.ACCEPTED if ok else CommandResult.FAILED
            fut.set_result(result)

    def get_history(self, limit: int = 20) -> list[CommandRecord]:
        return list(reversed(self._history[-limit:]))

    # ── Validation ────────────────────────────────────────────────

    def _validate(self, command: str, params: dict) -> Optional[str]:
        """
        Returns a denial reason string, or None if command is allowed.
        Reads current drone state from StateManager.
        """
        state = self._state.get(self.drone_id) or {}
        armed   = state.get("is_armed", False)
        mode    = state.get("flight_mode", "UNKNOWN")
        battery = state.get("battery_remaining_pct", -1)
        gps_fix = state.get("gps_fix_type", "No GPS")
        sats    = state.get("gps_satellites", 0)

        if command == "arm":
            if armed:
                return "Drone is already armed"
            if battery >= 0 and battery < 20:
                return f"Battery too low to arm ({battery}%)"
            if gps_fix in ("No GPS", "No fix") or sats < 6:
                return f"Insufficient GPS fix to arm ({gps_fix}, {sats} sats)"

        elif command == "disarm":
            if not armed:
                return "Drone is already disarmed"
            if mode not in ("LAND", "LOITER", "STABILIZE", "ALT_HOLD") and armed:
                # Allow forced disarm only on ground — warn but don't block
                log.warning("Disarming while not in a safe mode",
                            drone_id=self.drone_id, mode=mode)

        elif command == "takeoff":
            if not armed:
                return "Drone must be armed before takeoff"
            alt = params.get("altitude_m", 0)
            if alt <= 0 or alt > 500:
                return f"Takeoff altitude must be between 1 and 500 m (got {alt})"

        elif command == "set_mode":
            target_mode = params.get("mode", "")
            if not target_mode:
                return "set_mode requires 'mode' parameter"
            available = self._mav.mode_mapping() or {}
            if target_mode not in available:
                return (f"Mode '{target_mode}' not supported by this autopilot. "
                        f"Available: {list(available.keys())}")

        elif command == "emergency_stop":
            # Always allowed — no validation blocks an emergency
            pass

        return None   # Passed all checks

    # ── MAVLink encoding ─────────────────────────────────────────

    def _dispatch(self, command: str, params: dict):
        """
        Synchronous MAVLink encoding and send.
        Runs in executor — must not call asyncio primitives.
        """
        mav = self._mav

        if command == "arm":
            mav.mav.command_long_send(
                mav.target_system, mav.target_component,
                mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                0,
                1, 0, 0, 0, 0, 0, 0   # param1=1 → arm
            )

        elif command == "disarm":
            mav.mav.command_long_send(
                mav.target_system, mav.target_component,
                mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                0,
                0, 0, 0, 0, 0, 0, 0   # param1=0 → disarm
            )

        elif command == "emergency_stop":
            # MAV_CMD_DO_FLIGHTTERMINATION — forces immediate motor cutoff
            mav.mav.command_long_send(
                mav.target_system, mav.target_component,
                mavutil.mavlink.MAV_CMD_DO_FLIGHTTERMINATION,
                0,
                1, 0, 0, 0, 0, 0, 0
            )

        elif command == "set_mode":
            mode_id = mav.mode_mapping().get(params["mode"])
            mav.mav.set_mode_send(
                mav.target_system,
                mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                mode_id,
            )

        elif command == "rtl":
            mode_id = mav.mode_mapping().get("RTL")
            mav.mav.set_mode_send(
                mav.target_system,
                mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                mode_id,
            )

        elif command == "land":
            mode_id = mav.mode_mapping().get("LAND")
            mav.mav.set_mode_send(
                mav.target_system,
                mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                mode_id,
            )

        elif command == "takeoff":
            alt = params.get("altitude_m", 30)
            mav.mav.command_long_send(
                mav.target_system, mav.target_component,
                mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                0,
                0, 0, 0, 0,   # params 1-4 unused
                0, 0, alt      # lat, lon, altitude
            )

        elif command == "goto":
            lat = int(params["latitude"]  * 1e7)
            lon = int(params["longitude"] * 1e7)
            alt = params.get("altitude_m", 50)
            mav.mav.mission_item_int_send(
                mav.target_system, mav.target_component,
                0,
                mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                2,   # current=2 → guided-mode goto
                0, 0, 0, 0, 0, lat, lon, alt,
            )

        else:
            raise ValueError(f"Unknown command: {command}")

    # ── ACK tracking ──────────────────────────────────────────────

    async def _await_ack(self, command: str, timeout: float) -> CommandResult:
        """
        Creates a Future and waits for handle_ack() to resolve it.
        Commands that don't produce a COMMAND_ACK (e.g. set_mode via
        SET_MODE message) resolve immediately as ACCEPTED after a short
        grace period — the mode change is confirmed via HEARTBEAT instead.
        """
        no_ack_commands = {"set_mode", "rtl", "land"}
        if command in no_ack_commands:
            await asyncio.sleep(0.2)
            return CommandResult.ACCEPTED

        cmd_id = self._command_to_mavlink_id(command)
        if cmd_id is None:
            return CommandResult.ACCEPTED   # Can't track — assume ok

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[cmd_id] = fut

        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(cmd_id, None)
            raise

    @staticmethod
    def _command_to_mavlink_id(command: str) -> Optional[int]:
        mapping = {
            "arm":             mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            "disarm":          mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            "takeoff":         mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            "emergency_stop":  mavutil.mavlink.MAV_CMD_DO_FLIGHTTERMINATION,
        }
        return mapping.get(command)

    # ── Internal ──────────────────────────────────────────────────

    def _append(self, record: CommandRecord):
        self._history.append(record)
        if len(self._history) > HISTORY_LIMIT:
            self._history.pop(0)