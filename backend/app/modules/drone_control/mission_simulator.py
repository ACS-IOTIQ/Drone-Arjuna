"""
Mission Simulator
=================
Flies a saved mission without a physical drone by injecting synthetic
telemetry into the StateManager at 10 Hz.  The simulated drone appears
as a normal "connected" drone to all WebSocket subscribers and UI panels.

State machine
─────────────
IDLE → ARMED (arm) → TAKEOFF (takeoff/AUTO) → FLYING → PAUSED (loiter)
FLYING → RTL (rtl) → LANDED
FLYING → LANDING (land) → LANDED
Any → IDLE (emergency_stop / stop)
"""
import asyncio
import math
import time
from enum import Enum
from typing import Optional
import structlog

from app.utils.geofence import geofence_store
from app.core.events import emit_geofence_breach, emit_geofence_recovered

log = structlog.get_logger()

EARTH_R = 6_371_000.0  # metres


# ── Geography helpers ─────────────────────────────────────────────

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(min(a, 1.0)))


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlon = math.radians(lon2 - lon1)
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlon) * math.cos(lat2r)
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _move_toward(lat: float, lon: float, bearing: float, dist_m: float):
    d = dist_m / EARTH_R
    br = math.radians(bearing)
    lat1, lon1 = math.radians(lat), math.radians(lon)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(br)
    )
    lon2 = lon1 + math.atan2(
        math.sin(br) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


# ── State machine ─────────────────────────────────────────────────

class SimPhase(str, Enum):
    IDLE    = "idle"
    ARMED   = "armed"
    TAKEOFF = "takeoff"
    FLYING  = "flying"
    PAUSED  = "paused"
    RTL     = "rtl"
    LANDING = "landing"
    LANDED  = "landed"


_PHASE_MODE = {
    SimPhase.IDLE:    "STABILIZE",
    SimPhase.ARMED:   "STABILIZE",
    SimPhase.TAKEOFF: "GUIDED",
    SimPhase.FLYING:  "AUTO",
    SimPhase.PAUSED:  "LOITER",
    SimPhase.RTL:     "RTL",
    SimPhase.LANDING: "LAND",
    SimPhase.LANDED:  "LAND",
}


class MissionSimulator:
    """
    Module-level singleton that manages one active simulation at a time.
    Multiple concurrent simulations are not supported.
    """
    TICK_HZ     = 10
    CRUISE_MS   = 10.0   # default cruise speed m/s
    CLIMB_MS    = 2.5    # takeoff climb rate m/s
    DESCENT_MS  = 1.5    # landing descent rate m/s
    BATT_DRAIN  = 0.015  # % per second at cruise
    WP_RADIUS_M = 3.0    # waypoint arrival acceptance radius
    HOME_MSL    = 50.0   # assumed ground elevation above sea level

    def __init__(self):
        self._sm   = None   # StateManager injected on start()
        self._task: Optional[asyncio.Task] = None
        self._cmds: asyncio.Queue = asyncio.Queue()
        self._breaching: dict[int, bool] = {}   # per-drone breach state for edge detection

        self.phase      = SimPhase.IDLE
        self.drone_id:  Optional[int] = None
        self.call_sign  = ""
        self.waypoints: list = []
        self.speed_mult = 1.0
        self.wp_idx     = 0

        self.lat         = 0.0
        self.lon         = 0.0
        self.alt         = 0.0   # AGL metres
        self.heading     = 0.0
        self.pitch       = 0.0
        self.roll        = 0.0
        self.airspeed    = 0.0
        self.groundspeed = 0.0
        self.climb_rate  = 0.0
        self.throttle    = 0.0
        self.is_armed    = False
        self.battery_pct = 100.0

        self._home_lat   = 0.0
        self._home_lon   = 0.0
        self._target_alt = 30.0

    # ── Public API ────────────────────────────────────────────────

    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    def get_status(self) -> dict:
        return {
            "active":           self.active,
            "phase":            self.phase.value,
            "drone_id":         self.drone_id,
            "call_sign":        self.call_sign,
            "waypoint_index":   self.wp_idx,
            "waypoint_count":   len(self.waypoints),
            "progress":         self.wp_idx / len(self.waypoints) if self.waypoints else 0.0,
            "speed_multiplier": self.speed_mult,
        }

    async def start(
        self,
        drone_id:   int,
        call_sign:  str,
        waypoints:  list,
        home_lat:   float,
        home_lon:   float,
        speed_mult: float = 1.0,
        state_mgr=None,
    ):
        if self.active:
            await self.stop()

        if state_mgr:
            self._sm = state_mgr

        self.drone_id   = drone_id
        self.call_sign  = call_sign
        self.waypoints  = waypoints
        self.speed_mult = max(0.1, min(speed_mult, 20.0))
        self._home_lat  = home_lat
        self._home_lon  = home_lon
        self.lat        = home_lat
        self.lon        = home_lon
        self.alt        = 0.0
        self.heading    = 0.0
        self.battery_pct = 100.0
        self.is_armed   = False
        self.phase      = SimPhase.IDLE
        self.wp_idx     = 0

        self._sm.init_drone(drone_id, call_sign)

        while not self._cmds.empty():
            self._cmds.get_nowait()

        self._task = asyncio.create_task(self._run(), name=f"sim-{call_sign}")
        log.info("Simulation started", drone_id=drone_id, waypoints=len(waypoints),
                 speed_mult=self.speed_mult)

    async def command(self, action: str, params: dict = {}):
        await self._cmds.put((action, params))

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self.drone_id is not None and self._sm:
            self._sm.remove_drone(self.drone_id)
        self.phase    = SimPhase.IDLE
        self._task    = None
        self.drone_id = None
        log.info("Simulation stopped")

    # ── Main loop ─────────────────────────────────────────────────

    async def _run(self):
        dt = 1.0 / self.TICK_HZ
        try:
            while True:
                t0 = time.monotonic()
                while not self._cmds.empty():
                    action, params = self._cmds.get_nowait()
                    self._handle_cmd(action, params)
                self._tick(dt)
                await self._push()
                if self.phase == SimPhase.LANDED:
                    await asyncio.sleep(3.0)
                    break
                elapsed = time.monotonic() - t0
                await asyncio.sleep(max(0.0, dt - elapsed))
        except asyncio.CancelledError:
            raise
        finally:
            log.info("Sim loop exited", drone_id=self.drone_id)

    # ── Command handler ───────────────────────────────────────────

    def _handle_cmd(self, action: str, params: dict):
        if action == "arm":
            if self.phase == SimPhase.IDLE:
                self.is_armed = True
                self.phase    = SimPhase.ARMED

        elif action == "disarm":
            if self.phase in (SimPhase.ARMED, SimPhase.LANDED):
                self.is_armed = False
                self.phase    = SimPhase.IDLE

        elif action == "takeoff":
            if self.phase == SimPhase.ARMED:
                alt = float(params.get("altitude", 30.0))
                if self.waypoints:
                    alt = float(self.waypoints[0].get("altitude_m", alt))
                self._target_alt = alt
                self.phase = SimPhase.TAKEOFF

        elif action == "set_mode":
            mode = params.get("mode", "")
            if mode == "AUTO" and self.phase in (SimPhase.ARMED,):
                self._target_alt = float(self.waypoints[0]["altitude_m"]) if self.waypoints else 30.0
                self.phase = SimPhase.TAKEOFF
            elif mode == "RTL":
                self.phase = SimPhase.RTL
            elif mode == "LAND":
                self.phase = SimPhase.LANDING
            elif mode == "LOITER" and self.phase == SimPhase.FLYING:
                self.phase = SimPhase.PAUSED
            elif mode in ("AUTO", "STABILIZE") and self.phase == SimPhase.PAUSED:
                self.phase = SimPhase.FLYING

        elif action == "rtl":
            self.phase = SimPhase.RTL

        elif action == "land":
            self.phase = SimPhase.LANDING

        elif action == "emergency_stop":
            self.is_armed    = False
            self.throttle    = 0.0
            self.groundspeed = 0.0
            self.airspeed    = 0.0
            self.climb_rate  = 0.0
            self.alt         = 0.0
            self.phase       = SimPhase.LANDED

    # ── Physics tick ──────────────────────────────────────────────

    def _tick(self, dt: float):
        if self.phase == SimPhase.IDLE:
            self.throttle = 0.0; self.groundspeed = 0.0
            self.airspeed = 0.0; self.climb_rate  = 0.0

        elif self.phase == SimPhase.ARMED:
            self.throttle    = 22.0
            self.groundspeed = 0.0
            self.airspeed    = 0.0
            self.climb_rate  = 0.0

        elif self.phase == SimPhase.TAKEOFF:
            climb       = self.CLIMB_MS * self.speed_mult
            self.alt   += climb * dt
            self.climb_rate = climb
            self.throttle   = 78.0
            self.airspeed   = 2.0
            self.pitch      = 12.0
            if self.alt >= self._target_alt:
                self.alt        = self._target_alt
                self.climb_rate = 0.0
                self.pitch      = 0.0
                self.phase      = SimPhase.FLYING
                if self.waypoints:
                    wp = self.waypoints[self.wp_idx]
                    self.heading = _bearing_deg(self.lat, self.lon,
                                                wp["latitude"], wp["longitude"])

        elif self.phase == SimPhase.FLYING:
            if not self.waypoints or self.wp_idx >= len(self.waypoints):
                self.phase = SimPhase.LANDING
                return
            wp     = self.waypoints[self.wp_idx]
            t_lat  = float(wp["latitude"])
            t_lon  = float(wp["longitude"])
            t_alt  = float(wp.get("altitude_m", 30.0))
            spd    = float(wp.get("speed_ms") or self.CRUISE_MS) * self.speed_mult

            dist = _haversine_m(self.lat, self.lon, t_lat, t_lon)
            tgt_hdg = _bearing_deg(self.lat, self.lon, t_lat, t_lon) if dist > 0.5 else self.heading

            # Smooth heading — max 25°/s
            hdg_err  = ((tgt_hdg - self.heading + 180) % 360) - 180
            turn     = max(min(hdg_err, 25.0 * dt), -25.0 * dt)
            self.heading = (self.heading + turn) % 360

            if dist > 1.0:
                self.lat, self.lon = _move_toward(
                    self.lat, self.lon, self.heading, min(spd * dt, dist)
                )

            alt_err      = t_alt - self.alt
            max_vert     = 4.0 * self.speed_mult * dt
            self.alt    += max(min(alt_err, max_vert), -max_vert)
            self.climb_rate = (
                max(min(alt_err / 0.5, 4.0 * self.speed_mult), -4.0 * self.speed_mult)
                if abs(alt_err) > 0.2 else 0.0
            )
            self.pitch       = max(min(alt_err * 0.4, 15.0), -12.0)
            self.roll        = max(min(hdg_err * 0.25, 30.0), -30.0)
            self.groundspeed = float(wp.get("speed_ms") or self.CRUISE_MS)
            self.airspeed    = self.groundspeed + (1.0 if alt_err > 1.0 else 0.0)
            self.throttle    = 60.0 + (15.0 if alt_err > 2.0 else 0.0)
            self.battery_pct = max(0.0, self.battery_pct - self.BATT_DRAIN * dt)

            if dist < self.WP_RADIUS_M and abs(alt_err) < 3.0:
                self.wp_idx += 1
                if self.wp_idx >= len(self.waypoints):
                    self.phase = SimPhase.LANDING

        elif self.phase == SimPhase.PAUSED:
            self.heading     = (self.heading + 3.0 * dt * self.speed_mult) % 360
            self.groundspeed = 4.0
            self.airspeed    = 4.0
            self.climb_rate  = 0.0
            self.pitch       = 2.0
            self.roll        = 15.0
            self.battery_pct = max(0.0, self.battery_pct - self.BATT_DRAIN * 0.5 * dt)

        elif self.phase == SimPhase.RTL:
            dist = _haversine_m(self.lat, self.lon, self._home_lat, self._home_lon)
            if dist < 5.0 and self.alt < 2.0:
                self.alt = 0.0; self.groundspeed = 0.0
                self.climb_rate = 0.0; self.is_armed = False
                self.phase = SimPhase.LANDED
                return
            spd = self.CRUISE_MS * self.speed_mult
            hdg = _bearing_deg(self.lat, self.lon, self._home_lat, self._home_lon)
            self.heading = hdg
            if dist > 2.0:
                self.lat, self.lon = _move_toward(
                    self.lat, self.lon, hdg, min(spd * dt, dist)
                )
            if dist < 50.0:
                desc = self.DESCENT_MS * self.speed_mult
                self.alt        = max(0.0, self.alt - desc * dt)
                self.climb_rate = -desc
            self.groundspeed = self.CRUISE_MS
            self.airspeed    = self.CRUISE_MS
            self.throttle    = 55.0
            self.battery_pct = max(0.0, self.battery_pct - self.BATT_DRAIN * dt)

        elif self.phase == SimPhase.LANDING:
            desc             = self.DESCENT_MS * self.speed_mult
            self.alt         = max(0.0, self.alt - desc * dt)
            self.groundspeed = max(0.0, self.groundspeed * 0.97)
            self.airspeed    = self.groundspeed
            self.climb_rate  = -desc
            self.throttle    = max(20.0, self.throttle - 4.0 * dt)
            self.pitch       = -6.0
            if self.alt <= 0.05:
                self.alt = 0.0; self.groundspeed = 0.0; self.airspeed = 0.0
                self.climb_rate = 0.0; self.throttle = 0.0
                self.pitch = 0.0; self.roll = 0.0
                self.is_armed = False
                self.phase = SimPhase.LANDED

        elif self.phase == SimPhase.LANDED:
            pass

    # ── Telemetry push ────────────────────────────────────────────

    async def _push(self):
        if self.drone_id is None or self._sm is None:
            return
        await self._sm.update(self.drone_id, {
            "lat":                   self.lat,
            "lon":                   self.lon,
            "alt_msl":               self.alt + self.HOME_MSL,
            "alt_agl":               self.alt,
            "heading":               self.heading,
            "roll_deg":              self.roll,
            "pitch_deg":             self.pitch,
            "yaw_deg":               self.heading,
            "airspeed_ms":           self.airspeed,
            "groundspeed_ms":        self.groundspeed,
            "climb_rate_ms":         self.climb_rate,
            "throttle_pct":          self.throttle,
            "battery_voltage_v":     22.4 * (self.battery_pct / 100.0),
            "battery_remaining_pct": int(self.battery_pct),
            "battery_current_a":     8.5 if self.is_armed else 0.5,
            "gps_fix_type":          "3D Fix",
            "gps_satellites":        14,
            "gps_hdop":              0.8,
            "flight_mode":           _PHASE_MODE.get(self.phase, "UNKNOWN"),
            "is_armed":              self.is_armed,
            "rssi":                  95,
            "cpu_load_pct":          12.0,
            "call_sign":             self.call_sign,
            "connected":             True,
            # Simulation-specific extras (read by frontend overlay)
            "sim_phase":             self.phase.value,
            "sim_progress":          self.wp_idx / len(self.waypoints) if self.waypoints else 0.0,
            "sim_waypoint_idx":      self.wp_idx,
            "sim_waypoint_count":    len(self.waypoints),
        })
        await self._check_geofence()

    async def _check_geofence(self):
        """
        Edge-triggered geofence breach detection for the simulator.
        Mirrors TelemetryProcessor._check_geofence() but runs inside the
        simulator loop since simulated positions never go through MAVLink parsing.

        On breach  : injects geofence_breach=True into state (→ WebSocket),
                     publishes to RabbitMQ, and transitions to RTL phase.
        On recovery: injects geofence_breach=False into state, publishes recovery event.
        """
        if self.drone_id is None or self._sm is None:
            return
        inside = geofence_store.is_inside(self.drone_id, self.lat, self.lon)
        if inside is None:
            return  # no fence registered for this drone

        was_breaching = self._breaching.get(self.drone_id, False)
        now_breaching = not inside

        if now_breaching and not was_breaching:
            self._breaching[self.drone_id] = True
            log.warning(
                "Sim geofence breach",
                drone_id=self.drone_id,
                lat=self.lat,
                lon=self.lon,
            )
            await self._sm.update(self.drone_id, {
                "geofence_breach": True,
                "breach_lat":      self.lat,
                "breach_lon":      self.lon,
            })
            await emit_geofence_breach(self.drone_id, self.lat, self.lon)
            # Auto-RTL: transition the simulated drone back to home
            if self.phase == SimPhase.FLYING:
                self.phase = SimPhase.RTL
                log.warning("Auto-RTL triggered — sim geofence breach", drone_id=self.drone_id)

        elif not now_breaching and was_breaching:
            self._breaching[self.drone_id] = False
            log.info("Sim drone recovered inside geofence", drone_id=self.drone_id)
            await self._sm.update(self.drone_id, {"geofence_breach": False})
            await emit_geofence_recovered(self.drone_id)


# Module-level singleton
mission_simulator = MissionSimulator()
