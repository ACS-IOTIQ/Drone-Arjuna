"""
HF Link Adapter
===============
Manages the HF radio datalink tier for ship-to-shore drone operations.

Key responsibilities:
  - MAVLink message priority queue (position/battery/health at 1-2 Hz;
    suppress non-essential messages to stay within HF bandwidth)
  - HF-specific heartbeat and command-ACK timeout values
  - Degraded-HF state distinct from link-lost (ionospheric blackout handling)
  - Thin abstraction over HF modem ALE interface (Harris/Codan/Barrett)

Bandwidth constraint: military HF typically delivers 1.2–9.6 kbps in practice.
At 2 Hz telemetry, lean MAVLink v2 packets consume ~2–3 kbps per drone —
leaving headroom for commands and vessel position updates.
"""
import asyncio
import time
import structlog
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = structlog.get_logger()


# ── Message priority tiers ────────────────────────────────────────────────────

class MsgPriority(int, Enum):
    CRITICAL  = 0   # ARM/DISARM, RTL, emergency — always pass through immediately
    HIGH      = 1   # Position, battery, attitude at 1-2 Hz
    MEDIUM    = 2   # Mode, GPS status at 0.5 Hz
    LOW       = 3   # STATUSTEXT, PARAM_VALUE, non-essential — suppress on HF

# MAVLink message type → priority mapping
MSG_PRIORITY: dict[str, MsgPriority] = {
    # Critical flight safety
    "COMMAND_ACK":          MsgPriority.CRITICAL,
    "HEARTBEAT":            MsgPriority.HIGH,

    # High — position and health at 1-2 Hz over HF
    "GLOBAL_POSITION_INT":  MsgPriority.HIGH,
    "GPS_RAW_INT":          MsgPriority.HIGH,
    "BATTERY_STATUS":       MsgPriority.HIGH,
    "SYS_STATUS":           MsgPriority.HIGH,
    "ATTITUDE":             MsgPriority.HIGH,

    # Medium — send at 0.5 Hz
    "VFR_HUD":              MsgPriority.MEDIUM,
    "MISSION_CURRENT":      MsgPriority.MEDIUM,
    "NAV_CONTROLLER_OUTPUT": MsgPriority.MEDIUM,

    # Low — suppressed on HF to preserve bandwidth for critical traffic
    "STATUSTEXT":           MsgPriority.LOW,
    "PARAM_VALUE":          MsgPriority.LOW,
    "MISSION_ITEM_REACHED": MsgPriority.LOW,
    "SERVO_OUTPUT_RAW":     MsgPriority.LOW,
    "RC_CHANNELS":          MsgPriority.LOW,
    "RAW_IMU":              MsgPriority.LOW,
    "SCALED_IMU2":          MsgPriority.LOW,
}

# Per-priority minimum interval between forwarded messages (seconds)
HF_RATE_LIMITS: dict[MsgPriority, float] = {
    MsgPriority.CRITICAL: 0.0,    # Never rate-limited
    MsgPriority.HIGH:     0.5,    # max 2 Hz
    MsgPriority.MEDIUM:   2.0,    # max 0.5 Hz
    MsgPriority.LOW:      float("inf"),  # blocked on HF
}


# ── HF link state machine ─────────────────────────────────────────────────────

class HFLinkState(str, Enum):
    CONNECTED   = "connected"    # Normal HF operation
    DEGRADED    = "degraded"     # Blackout / ALE re-linking — drone continues autonomously
    LOST        = "lost"         # Link down beyond degraded threshold — failsafe applies


# ── HF-specific timeout defaults ─────────────────────────────────────────────

HF_HEARTBEAT_TIMEOUT_S  = 45.0   # vs 5 s for short-range RF — HF ALE can take 10-30 s
HF_COMMAND_ACK_TIMEOUT_S = 8.0   # vs 1-2 s for short-range RF
HF_DEGRADED_THRESHOLD_S  = 20.0  # blackout duration before entering DEGRADED
HF_LOST_THRESHOLD_S      = 120.0 # DEGRADED duration before entering LOST


# ── Priority queue entry ──────────────────────────────────────────────────────

@dataclass(order=True)
class QueueEntry:
    priority: int          # lower = higher priority
    timestamp: float       # used for tie-breaking
    msg_type: str = field(compare=False)
    msg: object = field(compare=False)


# ── HFLinkAdapter ─────────────────────────────────────────────────────────────

class HFLinkAdapter:
    """
    Wraps an underlying MAVLink connection with HF-appropriate behaviours.
    Instantiated by MAVLinkManager when transport='hf_serial' or 'hf_tcp'.
    """

    def __init__(self, drone_id: int, modem_type: str = "generic"):
        self.drone_id    = drone_id
        self.modem_type  = modem_type
        self.state       = HFLinkState.CONNECTED
        self._last_rx    = time.monotonic()
        self._degraded_at: Optional[float] = None
        self._last_sent: dict[MsgPriority, float] = {p: 0.0 for p in MsgPriority}

        # SNR/BER metrics updated by modem ALE interface if available
        self.snr_db: Optional[float] = None
        self.ber: Optional[float] = None

    # ── Message filtering ─────────────────────────────────────────

    def should_forward(self, msg_type: str) -> bool:
        """
        Returns True if the message should be forwarded to the GCS over HF.
        Applies rate limiting per priority tier to stay within HF bandwidth.
        """
        priority = MSG_PRIORITY.get(msg_type, MsgPriority.LOW)
        min_interval = HF_RATE_LIMITS[priority]

        if min_interval == float("inf"):
            return False  # blocked tier

        now = time.monotonic()
        if (now - self._last_sent[priority]) >= min_interval:
            self._last_sent[priority] = now
            return True
        return False

    # ── Heartbeat / link state management ────────────────────────

    def on_message_received(self):
        """Call on every received MAVLink message to track link liveness."""
        now = time.monotonic()
        self._last_rx = now
        if self.state != HFLinkState.CONNECTED:
            log.info("HF link restored", drone_id=self.drone_id, state=self.state)
            self.state = HFLinkState.CONNECTED
            self._degraded_at = None

    def tick(self) -> HFLinkState:
        """
        Advance the HF state machine. Call periodically (e.g. every 5 s).
        Returns the current state.
        """
        now = time.monotonic()
        silence_s = now - self._last_rx

        if silence_s < HF_DEGRADED_THRESHOLD_S:
            if self.state != HFLinkState.CONNECTED:
                self.state = HFLinkState.CONNECTED
                self._degraded_at = None
            return self.state

        if silence_s < HF_LOST_THRESHOLD_S:
            if self.state == HFLinkState.CONNECTED:
                self.state = HFLinkState.DEGRADED
                self._degraded_at = now
                log.warning("HF link DEGRADED (blackout / ALE re-linking)",
                            drone_id=self.drone_id, silence_s=round(silence_s, 1))
            return self.state

        if self.state != HFLinkState.LOST:
            self.state = HFLinkState.LOST
            log.error("HF link LOST — failsafe may apply",
                      drone_id=self.drone_id, silence_s=round(silence_s, 1))
        return self.state

    # ── Modem ALE interface ───────────────────────────────────────

    def update_link_quality(self, snr_db: Optional[float], ber: Optional[float]):
        """Receive SNR/BER from the modem ALE interface and log if poor."""
        self.snr_db = snr_db
        self.ber    = ber
        if snr_db is not None and snr_db < 5.0:
            log.warning("Poor HF SNR", drone_id=self.drone_id, snr_db=snr_db)

    def get_status(self) -> dict:
        return {
            "drone_id":   self.drone_id,
            "link_type":  "hf",
            "state":      self.state.value,
            "modem_type": self.modem_type,
            "snr_db":     self.snr_db,
            "ber":        self.ber,
            "silence_s":  round(time.monotonic() - self._last_rx, 1),
            "heartbeat_timeout_s":   HF_HEARTBEAT_TIMEOUT_S,
            "command_ack_timeout_s": HF_COMMAND_ACK_TIMEOUT_S,
        }


# ── Module-level registry: one adapter per HF-linked drone ───────────────────

_hf_adapters: dict[int, HFLinkAdapter] = {}


def get_or_create(drone_id: int, modem_type: str = "generic") -> HFLinkAdapter:
    if drone_id not in _hf_adapters:
        _hf_adapters[drone_id] = HFLinkAdapter(drone_id, modem_type)
    return _hf_adapters[drone_id]


def remove(drone_id: int):
    _hf_adapters.pop(drone_id, None)


def get_all_statuses() -> list[dict]:
    return [a.get_status() for a in _hf_adapters.values()]


async def run_tick_loop(interval_s: float = 5.0):
    """
    Background coroutine — advance all HF adapter state machines periodically.
    Started by drone_control events on app startup alongside other background tasks.
    """
    while True:
        await asyncio.sleep(interval_s)
        for adapter in list(_hf_adapters.values()):
            adapter.tick()
