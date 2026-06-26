"""
Mission Planner
===============
Business logic for the Drone Flight module.

Responsibilities:
  - Mission validation against drone type performance limits
  - MAVLink mission upload to the vehicle
  - Survey grid generation from a polygon area
  - Pre-flight simulation frame generation (frontend animation)
  - Mission execution control (start, pause, abort)

Distinct from:
  geo_service.py  — pure geometry (haversine, battery estimate)
  router.py       — HTTP adapter only
"""
import math
import asyncio
import structlog
from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from pymavlink import mavutil
from shapely import from_wkt, convex_hull as shapely_convex_hull

from app.models.mission import Mission, Waypoint
from app.models.drone import DroneType, DroneInstance
from app.models.vessel import NavalVessel
from app.modules.drone_flight.geo_service import haversine_m, CRUISE_SPEED_MS
from app.modules.drone_control.mavlink_manager import mavlink_manager
from app.utils.geo_utils import (
    point_in_polygon, geojson_polygon_to_ring, bearing_deg,
)
from app.utils.geofence import geofence_store

log = structlog.get_logger()

KNOTS_TO_MS = 0.514444


# ══════════════════════════════════════════════════════════════════
# Mission deconfliction
# ══════════════════════════════════════════════════════════════════

def deconflict_missions(
    missions_with_waypoints: list[tuple["Mission", list["Waypoint"]]],
) -> list[dict]:
    """
    Check all pairs of missions for 2-D airspace conflict using
    Shapely convex hulls built from each mission's waypoints.

    Returns a list of conflict dicts — one entry per conflicting pair:
        {
            "mission_a_id": int,
            "mission_a_name": str,
            "mission_b_id": int,
            "mission_b_name": str,
            "overlap_area_km2": float,   # 0.0 for line/point intersections
        }

    An empty list means no conflicts.

    Only missions with at least one waypoint participate. Missions
    whose hull is a point or line segment still contribute — their
    intersection with another hull may be non-empty even without area.
    """
    # Build (mission, convex_hull) pairs — skip missions with no waypoints
    hulls: list[tuple[Mission, object]] = []
    for mission, waypoints in missions_with_waypoints:
        if not waypoints:
            continue
        # Build a MULTIPOINT via WKT — bypasses shapely.multipoints() /
        # create_collection, which fails in Shapely 2.0.4 on this GEOS build
        # due to a numpy object-array dtype incompatibility.
        wkt = "MULTIPOINT (" + ", ".join(
            f"({wp.longitude} {wp.latitude})" for wp in waypoints
        ) + ")"
        hull = shapely_convex_hull(from_wkt(wkt))
        hulls.append((mission, hull))

    conflicts: list[dict] = []
    for i in range(len(hulls)):
        for j in range(i + 1, len(hulls)):
            m_a, hull_a = hulls[i]
            m_b, hull_b = hulls[j]

            intersection = hull_a.intersection(hull_b)
            if intersection.is_empty:
                continue

            # touches() = boundary-only contact (no interior overlap) — not a conflict
            if hull_a.touches(hull_b):
                continue

            # Convert intersection area from degrees² to km²
            # 1 degree ≈ 111.32 km at the equator; use midpoint latitude for correction
            mid_lat = (
                sum(wp.latitude for _, wps in missions_with_waypoints for wp in wps)
                / max(1, sum(len(wps) for _, wps in missions_with_waypoints))
            )
            deg2_to_km2 = (111.32 ** 2) * math.cos(math.radians(mid_lat))
            overlap_km2 = round(intersection.area * deg2_to_km2, 4)

            conflicts.append({
                "mission_a_id":   m_a.id,
                "mission_a_name": m_a.name,
                "mission_b_id":   m_b.id,
                "mission_b_name": m_b.name,
                "overlap_area_km2": overlap_km2,
            })
            log.warning(
                "Mission deconfliction — airspace conflict detected",
                mission_a=m_a.id,
                mission_b=m_b.id,
                overlap_km2=overlap_km2,
            )

    return conflicts


def _project_vessel_position(
    vessel: NavalVessel, elapsed_s: float
) -> tuple[float, float]:
    """
    Project the vessel's position forward by `elapsed_s` seconds using
    its current heading and speed.  Returns (lat, lon).
    Falls back to current position if heading/speed are unavailable.
    """
    if vessel.heading_deg is None or vessel.speed_kts is None or vessel.speed_kts == 0:
        return (vessel.latitude, vessel.longitude)

    speed_ms   = vessel.speed_kts * KNOTS_TO_MS
    distance_m = speed_ms * elapsed_s
    heading_r  = math.radians(vessel.heading_deg)

    # Flat-earth approximation (accurate within a few km)
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(vessel.latitude))

    delta_lat = (distance_m * math.cos(heading_r)) / m_per_deg_lat
    delta_lon = (distance_m * math.sin(heading_r)) / m_per_deg_lon

    return (vessel.latitude + delta_lat, vessel.longitude + delta_lon)


# ── Validation result ─────────────────────────────────────────────

@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.valid = False

    def add_warning(self, msg: str):
        self.warnings.append(msg)


# ── Simulation frame ──────────────────────────────────────────────

@dataclass
class SimFrame:
    """One animation tick for the pre-flight simulation."""
    t_s: float          # Seconds from mission start
    lat: float
    lon: float
    alt_m: float
    heading_deg: float
    speed_ms: float
    battery_pct: float
    waypoint_idx: int   # Index of the waypoint being approached


# ══════════════════════════════════════════════════════════════════
# MissionValidator
# ══════════════════════════════════════════════════════════════════

class MissionValidator:
    """
    Validates a mission plan against the assigned drone's
    performance specification before approval or execution.
    """

    # Margins applied on top of raw estimates
    BATTERY_RESERVE_PCT = 20.0   # Always keep 20% in reserve
    ALTITUDE_MARGIN_M   = 50.0   # Stay this far below drone ceiling

    def __init__(self, db: AsyncSession):
        self.db = db

    async def validate(
        self,
        mission: Mission,
        waypoints: list[Waypoint],
        drone_type: Optional[DroneType] = None,
        vessel: Optional[NavalVessel] = None,
    ) -> ValidationResult:
        result = ValidationResult(valid=True)

        # ── 1. Structural checks (no drone required) ────────────────
        self._check_waypoints(waypoints, result)

        if not result.valid:
            return result   # Don't continue with empty/broken waypoint set

        # ── 2. Geofence compliance ──────────────────────────────────
        if mission.geofence:
            self._check_geofence(waypoints, mission.geofence, result)

        # ── 3. Drone-specific limits ────────────────────────────────
        if drone_type:
            self._check_payload_weight(mission, drone_type, result)
            self._check_altitude_limits(waypoints, drone_type, result)
            self._check_speed_limits(waypoints, drone_type, result)
            self._check_battery_budget(waypoints, drone_type, result, vessel=vessel)

        # ── 4. Dynamic home point advisory ─────────────────────────
        if mission.home_point_type == "dynamic_vessel":
            if vessel is None:
                result.add_error("Mission uses dynamic_vessel home point but no vessel is assigned")
            elif vessel.latitude is None:
                result.add_warning(
                    f"Vessel '{vessel.vessel_id}' has no current position — "
                    f"return-to-ship distance cannot be estimated"
                )

        return result

    # ── Structural ────────────────────────────────────────────────

    def _check_waypoints(self, wps: list[Waypoint], r: ValidationResult):
        if not wps:
            r.add_error("Mission has no waypoints")
            return
        if len(wps) < 2:
            r.add_error("Mission needs at least 2 waypoints (home + one target)")
        home_count = sum(1 for w in wps if w.is_home)
        if home_count == 0:
            r.add_error("Mission has no home/takeoff waypoint (is_home=True)")
        if home_count > 1:
            r.add_error(f"Mission has {home_count} home waypoints — only 1 allowed")
        seqs = [w.sequence for w in wps]
        if len(seqs) != len(set(seqs)):
            r.add_error("Duplicate waypoint sequence numbers found")

    # ── Geofence ──────────────────────────────────────────────────

    def _check_geofence(self, wps: list[Waypoint], geofence: dict, r: ValidationResult):
        ring = geojson_polygon_to_ring(geofence)
        if ring is None:
            r.add_warning("Geofence format invalid — skipping geofence check")
            return
        for wp in wps:
            if not point_in_polygon(wp.latitude, wp.longitude, ring):
                r.add_error(
                    f"Waypoint {wp.sequence} ({wp.latitude:.5f}, {wp.longitude:.5f}) "
                    f"is outside the defined geofence"
                )

    # ── Payload weight ────────────────────────────────────────────

    def _check_payload_weight(
        self, mission: Mission, dt: DroneType, r: ValidationResult
    ):
        if not mission.payload_weight_kg:
            return
        if mission.payload_weight_kg > dt.max_payload_weight_kg:
            r.add_error(
                f"Payload weight {mission.payload_weight_kg} kg exceeds "
                f"{dt.name}'s max payload capacity {dt.max_payload_weight_kg} kg"
            )
        elif mission.payload_weight_kg > dt.max_payload_weight_kg * 0.9:
            r.add_warning(
                f"Payload weight {mission.payload_weight_kg} kg is within 10% of "
                f"{dt.name}'s max payload capacity {dt.max_payload_weight_kg} kg"
            )

    # ── Altitude ──────────────────────────────────────────────────

    def _check_altitude_limits(
        self, wps: list[Waypoint], dt: DroneType, r: ValidationResult
    ):
        ceiling = dt.max_altitude_m - self.ALTITUDE_MARGIN_M
        for wp in wps:
            if wp.altitude_m > ceiling:
                r.add_error(
                    f"Waypoint {wp.sequence} altitude {wp.altitude_m} m exceeds "
                    f"safe ceiling {ceiling} m for {dt.name}"
                )
            if wp.altitude_m < 0:
                r.add_error(f"Waypoint {wp.sequence} has negative altitude")

    # ── Speed ─────────────────────────────────────────────────────

    def _check_speed_limits(
        self, wps: list[Waypoint], dt: DroneType, r: ValidationResult
    ):
        for wp in wps:
            if wp.speed_ms and wp.speed_ms > dt.max_speed_ms:
                r.add_error(
                    f"Waypoint {wp.sequence} speed {wp.speed_ms} m/s exceeds "
                    f"max speed {dt.max_speed_ms} m/s for {dt.name}"
                )

    # ── Battery budget ────────────────────────────────────────────

    def _check_battery_budget(
        self,
        wps: list[Waypoint],
        dt: DroneType,
        r: ValidationResult,
        vessel: Optional[NavalVessel] = None,
    ):
        """
        Rough energy budget check using endurance as a proxy.
        When a vessel is provided (dynamic home point), the return leg
        uses the vessel's projected position at estimated return time
        rather than the static home waypoint coordinate.
        """
        if len(wps) < 2:
            return

        total_s = 0.0
        for i in range(len(wps) - 1):
            a, b = wps[i], wps[i + 1]
            dist_m = haversine_m(a.latitude, a.longitude, b.latitude, b.longitude)
            speed  = a.speed_ms or CRUISE_SPEED_MS
            total_s += dist_m / speed
            if b.loiter_time_s:
                total_s += b.loiter_time_s

        # For ship-based missions: adjust return distance using projected vessel position
        if vessel and vessel.latitude is not None and vessel.longitude is not None:
            projected = _project_vessel_position(vessel, total_s)
            last_wp = sorted(wps, key=lambda w: w.sequence)[-1]
            return_dist_m = haversine_m(
                last_wp.latitude, last_wp.longitude,
                projected[0], projected[1],
            )
            total_s += return_dist_m / CRUISE_SPEED_MS
            r.add_warning(
                f"Dynamic home point: vessel projected at "
                f"({projected[0]:.4f}, {projected[1]:.4f}) at return time "
                f"(~{total_s/60:.1f} min). Return leg distance: "
                f"{return_dist_m/1000:.1f} km."
            )

        available_s = dt.endurance_h * 3600 * (1 - self.BATTERY_RESERVE_PCT / 100)
        if total_s > available_s:
            r.add_error(
                f"Estimated flight time {total_s/60:.1f} min exceeds available "
                f"endurance {available_s/60:.1f} min (keeping {self.BATTERY_RESERVE_PCT}% reserve) "
                f"for {dt.name}"
            )
        elif total_s > available_s * 0.85:
            r.add_warning(
                f"Estimated flight time {total_s/60:.1f} min is within 15% of "
                f"available endurance — consider shorter route"
            )


# ══════════════════════════════════════════════════════════════════
# MissionPlanner
# ══════════════════════════════════════════════════════════════════

class MissionPlanner:
    """
    Builds missions, uploads them to drones, and controls execution.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._validator = MissionValidator(db)

    # ── Validation shortcut ───────────────────────────────────────

    async def validate_mission(
        self, mission: Mission, waypoints: list[Waypoint]
    ) -> ValidationResult:
        drone_type = await self._get_drone_type(mission.drone_instance_id)
        vessel = await self._get_home_vessel(mission)
        return await self._validator.validate(mission, waypoints, drone_type, vessel=vessel)

    # ── MAVLink mission upload ────────────────────────────────────

    async def upload_to_drone(
        self, mission: Mission, waypoints: list[Waypoint]
    ) -> dict:
        """
        Uploads the mission waypoint list to the drone as a MAVLink
        mission. The drone's onboard flight controller stores these
        and executes them when switched to AUTO mode.

        Steps:
          1. Validate mission
          2. Send MISSION_COUNT to open upload protocol
          3. Respond to MISSION_REQUEST for each item
          4. Confirm MISSION_ACK
        """
        if not mission.drone_instance_id:
            raise HTTPException(400, "Mission has no assigned drone")

        # Pre-upload validation
        result = await self.validate_mission(mission, waypoints)
        if not result.valid:
            raise HTTPException(
                422,
                {"message": "Mission validation failed", "errors": result.errors}
            )

        conn = mavlink_manager._connections.get(mission.drone_instance_id)
        if not conn or not conn.connected:
            raise HTTPException(503, "Assigned drone is not connected")

        # Arm runtime geofence so breach detection fires during execution
        geofence_store.set_geofence(mission.drone_instance_id, mission.geofence or None)

        # For ship-based missions, overwrite the home waypoint with current vessel position
        vessel = await self._get_home_vessel(mission)
        if vessel:
            waypoints = self._apply_dynamic_home(list(waypoints), vessel)

        mav  = conn.mav
        loop = asyncio.get_event_loop()

        try:
            items = self._build_mavlink_items(waypoints, mav)
            await loop.run_in_executor(
                None, lambda: self._send_mission_items(mav, items)
            )
            log.info("Mission uploaded", mission_id=mission.id,
                     drone_id=mission.drone_instance_id, items=len(items))
            return {
                "detail":    "Mission uploaded successfully",
                "items":     len(items),
                "warnings":  result.warnings,
            }
        except Exception as e:
            log.error("Mission upload failed", error=str(e))
            raise HTTPException(503, f"Mission upload failed: {e}")

    def _build_mavlink_items(self, waypoints: list[Waypoint], mav) -> list[dict]:
        """Converts Waypoint ORM objects to MAVLink mission item dicts."""
        items = []

        # Item 0 — home position (required by MAVLink protocol)
        home = next((w for w in waypoints if w.is_home), waypoints[0])
        items.append({
            "seq":     0,
            "frame":   mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            "command": mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
            "current": 0,
            "lat":     int(home.latitude  * 1e7),
            "lon":     int(home.longitude * 1e7),
            "alt":     home.altitude_m,
            "param1":  0, "param2": 0, "param3": 0, "param4": 0,
        })

        # Remaining waypoints
        for wp in sorted(waypoints, key=lambda w: w.sequence):
            if wp.is_home:
                continue

            cmd, p1, p2, p3, p4 = self._action_to_mavlink(wp)
            frame = (mavutil.mavlink.MAV_FRAME_GLOBAL_INT
                     if wp.altitude_ref == "MSL"
                     else mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT)

            items.append({
                "seq":     len(items),
                "frame":   frame,
                "command": cmd,
                "current": 0,
                "lat":     int(wp.latitude  * 1e7),
                "lon":     int(wp.longitude * 1e7),
                "alt":     wp.altitude_m,
                "param1":  p1, "param2": p2, "param3": p3, "param4": p4,
            })

        return items

    @staticmethod
    def _action_to_mavlink(wp: Waypoint) -> tuple:
        """Maps waypoint action to (MAVLink command, p1, p2, p3, p4)."""
        if wp.action == "loiter":
            return (mavutil.mavlink.MAV_CMD_NAV_LOITER_TIME,
                    wp.loiter_time_s or 10, 0, 0, 0)
        if wp.action == "land":
            return (mavutil.mavlink.MAV_CMD_NAV_LAND, 0, 0, 0, 0)
        if wp.action == "rtl":
            return (mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH, 0, 0, 0, 0)
        if wp.action == "photo":
            return (mavutil.mavlink.MAV_CMD_DO_DIGICAM_CONTROL, 0, 0, 0, 1)
        # Default: simple navigation waypoint
        speed = wp.speed_ms or 0
        return (mavutil.mavlink.MAV_CMD_NAV_WAYPOINT, 0, 0, 0, speed)

    @staticmethod
    def _send_mission_items(mav, items: list[dict]):
        """
        Synchronous mission upload protocol.
        Runs in executor — blocks until MISSION_ACK received.
        """
        count = len(items)
        mav.mav.mission_count_send(
            mav.target_system, mav.target_component, count
        )
        # Respond to MISSION_REQUEST / MISSION_REQUEST_INT messages
        for _ in range(count):
            msg = mav.recv_match(
                type=["MISSION_REQUEST", "MISSION_REQUEST_INT"],
                blocking=True, timeout=5
            )
            if not msg:
                raise TimeoutError("No MISSION_REQUEST received from drone")

            seq  = msg.seq
            item = items[seq]
            mav.mav.mission_item_int_send(
                mav.target_system, mav.target_component,
                item["seq"],
                item["frame"],
                item["command"],
                item["current"],
                1,               # autocontinue
                item["param1"], item["param2"],
                item["param3"], item["param4"],
                item["lat"],    item["lon"],
                item["alt"],
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION,
            )

        # Await final ACK
        ack = mav.recv_match(type="MISSION_ACK", blocking=True, timeout=5)
        if not ack:
            raise TimeoutError("No MISSION_ACK from drone after upload")
        if ack.type != mavutil.mavlink.MAV_MISSION_ACCEPTED:
            raise RuntimeError(f"Mission rejected by drone: MAV_MISSION_TYPE {ack.type}")

    # ── Survey grid generation ────────────────────────────────────

    @staticmethod
    def generate_survey_grid(
        polygon_latlon: list[tuple[float, float]],
        altitude_m: float,
        spacing_m: float = 50.0,
        angle_deg: float = 0.0,
        speed_ms: Optional[float] = None,
    ) -> list[dict]:
        """
        Generates a lawnmower survey grid from a polygon.
        Returns a list of waypoint dicts ready to be POSTed to /missions.

        Args:
            polygon_latlon: List of (lat, lon) tuples defining the survey area.
            altitude_m:     Survey altitude in metres AGL.
            spacing_m:      Lane spacing in metres (camera overlap dependent).
            angle_deg:      Grid angle in degrees (0 = north-south lanes).
            speed_ms:       Survey speed (None = use drone cruise speed).
        """
        if len(polygon_latlon) < 3:
            raise ValueError("Survey polygon needs at least 3 vertices")

        # Compute bounding box in a simple flat-earth approximation
        # (accurate enough for areas < ~50 km²)
        lats = [p[0] for p in polygon_latlon]
        lons = [p[1] for p in polygon_latlon]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)

        # metres per degree at this latitude
        centre_lat  = (min_lat + max_lat) / 2
        m_per_deg_lat = 111_320.0
        m_per_deg_lon = 111_320.0 * math.cos(math.radians(centre_lat))

        height_m = (max_lat - min_lat) * m_per_deg_lat
        width_m  = (max_lon - min_lon) * m_per_deg_lon

        # Generate scan lines
        waypoints = []
        seq       = 1
        y         = 0.0
        left_to_right = True

        while y <= height_m:
            lat = min_lat + y / m_per_deg_lat

            if left_to_right:
                start_lon, end_lon = min_lon, max_lon
            else:
                start_lon, end_lon = max_lon, min_lon

            waypoints.append({
                "sequence":     seq,
                "latitude":     round(lat, 7),
                "longitude":    round(start_lon, 7),
                "altitude_m":   altitude_m,
                "altitude_ref": "AGL",
                "speed_ms":     speed_ms,
                "action":       "none",
            })
            seq += 1

            waypoints.append({
                "sequence":     seq,
                "latitude":     round(lat, 7),
                "longitude":    round(end_lon, 7),
                "altitude_m":   altitude_m,
                "altitude_ref": "AGL",
                "speed_ms":     speed_ms,
                "action":       "photo",   # trigger camera at end of each lane
            })
            seq += 1

            y += spacing_m
            left_to_right = not left_to_right

        log.info("Survey grid generated",
                 lanes=seq // 2,
                 area_km2=round(height_m * width_m / 1e6, 3),
                 spacing_m=spacing_m)
        return waypoints

    # ── Pre-flight simulation ─────────────────────────────────────

    async def build_simulation(
        self,
        waypoints: list[Waypoint],
        battery_capacity_mah: float = 10_000,
        hover_current_a: float = 20.0,
        tick_s: float = 1.0,
    ) -> list[dict]:
        """
        Generates a sequence of SimFrames for the frontend animation.
        The frontend steps through these at real-time speed to preview
        the mission before execution.

        Returns a list of frame dicts, one per `tick_s` of flight.
        """
        if len(waypoints) < 2:
            return []

        sorted_wps = sorted(waypoints, key=lambda w: w.sequence)
        frames: list[dict] = []
        t = 0.0
        battery_mah = battery_capacity_mah

        for i in range(len(sorted_wps) - 1):
            a = sorted_wps[i]
            b = sorted_wps[i + 1]

            dist_m   = haversine_m(a.latitude, a.longitude, b.latitude, b.longitude)
            speed    = a.speed_ms or CRUISE_SPEED_MS
            seg_s    = dist_m / speed
            heading  = self._bearing(a.latitude, a.longitude, b.latitude, b.longitude)

            # Interpolate along this segment at tick_s intervals
            elapsed  = 0.0
            while elapsed < seg_s:
                frac = elapsed / seg_s
                lat  = a.latitude  + frac * (b.latitude  - a.latitude)
                lon  = a.longitude + frac * (b.longitude - a.longitude)
                alt  = a.altitude_m + frac * (b.altitude_m - a.altitude_m)

                # Battery drain: proportional to hover current × time
                drain = hover_current_a * (tick_s / 3600) * 1000  # mAh
                battery_mah = max(0.0, battery_mah - drain)
                battery_pct = (battery_mah / battery_capacity_mah) * 100

                frames.append({
                    "t_s":           round(t, 1),
                    "lat":           round(lat, 7),
                    "lon":           round(lon, 7),
                    "alt_m":         round(alt, 1),
                    "heading_deg":   round(heading, 1),
                    "speed_ms":      speed,
                    "battery_pct":   round(battery_pct, 1),
                    "waypoint_idx":  i,
                })

                t       += tick_s
                elapsed += tick_s

            # Loiter time at destination
            if b.loiter_time_s:
                loiter_elapsed = 0.0
                while loiter_elapsed < b.loiter_time_s:
                    drain       = hover_current_a * (tick_s / 3600) * 1000
                    battery_mah = max(0.0, battery_mah - drain)
                    battery_pct = (battery_mah / battery_capacity_mah) * 100
                    frames.append({
                        "t_s":           round(t, 1),
                        "lat":           round(b.latitude,  7),
                        "lon":           round(b.longitude, 7),
                        "alt_m":         round(b.altitude_m, 1),
                        "heading_deg":   round(heading, 1),
                        "speed_ms":      0.0,
                        "battery_pct":   round(battery_pct, 1),
                        "waypoint_idx":  i + 1,
                    })
                    t             += tick_s
                    loiter_elapsed += tick_s

        log.debug("Simulation built", frames=len(frames),
                  duration_min=round(t / 60, 1))
        return frames

    # ── Internal helpers ──────────────────────────────────────────

    async def _get_drone_type(
        self, drone_instance_id: Optional[int]
    ) -> Optional[DroneType]:
        if not drone_instance_id:
            return None
        inst = await self.db.get(DroneInstance, drone_instance_id)
        if not inst:
            return None
        return await self.db.get(DroneType, inst.drone_type_id)

    async def _get_home_vessel(self, mission: Mission) -> Optional[NavalVessel]:
        """Return the assigned vessel for dynamic-home missions, else None."""
        if mission.home_point_type != "dynamic_vessel" or not mission.home_vessel_id:
            return None
        return await self.db.get(NavalVessel, mission.home_vessel_id)

    @staticmethod
    def _apply_dynamic_home(
        waypoints: list[Waypoint], vessel: NavalVessel
    ) -> list[Waypoint]:
        """
        Replace the home waypoint's coordinates with the vessel's current position
        before MAVLink upload.  The drone's onboard flight computer stores this as
        the RTL target — subsequent position updates are pushed via
        DO_SET_HOME commands from the vessel_position_feed background task.
        """
        if vessel.latitude is None or vessel.longitude is None:
            raise HTTPException(
                503,
                f"Vessel '{vessel.vessel_id}' has no current position. "
                f"Cannot upload mission with dynamic home point."
            )
        for wp in waypoints:
            if wp.is_home:
                wp.latitude  = vessel.latitude
                wp.longitude = vessel.longitude
        return waypoints

    @staticmethod
    def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        return bearing_deg(lat1, lon1, lat2, lon2)