"""
Airspace Restriction Service
=============================
Single source of truth for government-regulated airspace zones in India.

Responsibilities:
  - Define all restricted zone data (airports, sensitive sites, border buffers)
  - Check whether a point (lat/lon) falls inside a restricted zone
  - Check whether a geofence polygon encloses a restricted zone center
  - Return structured violation reports used by the router (422 guard)
    and MissionValidator (validation errors)

Zone types:
  RED    — no-fly; Central Government permission required
  YELLOW — controlled; ATC / competent authority permission required

Sources:
  DigitalSky airspace map (DGCA / AAI / Ministry of Civil Aviation)
  PIB release on Drone Rules 2021 airspace classification
"""
import math
from dataclasses import dataclass
from typing import Optional


# ══════════════════════════════════════════════════════════════════
# Data model
# ══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AirspaceViolation:
    label: str        # e.g. "Waypoint 3" or "Geofence vertex 2"
    zone_name: str    # human-readable zone name
    zone_kind: str    # "red" | "yellow" | "sensitive"
    message: str      # full user-facing message


@dataclass(frozen=True)
class AirspaceCheckResult:
    violations: list[AirspaceViolation]

    @property
    def ok(self) -> bool:
        return len(self.violations) == 0

    @property
    def error_messages(self) -> list[str]:
        return [v.message for v in self.violations]


# ══════════════════════════════════════════════════════════════════
# Zone data
# ══════════════════════════════════════════════════════════════════

# (lat, lon, red_radius_m, yellow_radius_m, name)
AIRPORT_ZONES: list[tuple[float, float, float, float, str]] = [
    (23.8869, 91.2404,  5_000, 12_000, "Agartala Maharaja Bir Bikram Airport"),
    (27.1558, 77.9609,  5_000, 12_000, "Agra Airport"),
    (31.7096, 74.7973,  5_000, 12_000, "Amritsar Sri Guru Ram Dass Jee Airport"),
    (28.5562, 77.1000,  5_000, 12_000, "Delhi IGI Airport"),
    (19.0886, 72.8679,  5_000, 12_000, "Mumbai CSMIA Airport"),
    (17.2403, 78.4294,  5_000, 12_000, "Hyderabad RGIA Airport"),
    (13.1986, 77.7066,  5_000, 12_000, "Bengaluru Kempegowda Airport"),
    (12.9941, 80.1709,  5_000, 12_000, "Chennai International Airport"),
    (22.6547, 88.4467,  5_000, 12_000, "Kolkata NSCBI Airport"),
    (26.8242, 75.8122,  5_000, 12_000, "Jaipur International Airport"),
    (22.3092, 70.7795,  5_000, 12_000, "Rajkot Airport"),
    (23.0734, 72.6266,  5_000, 12_000, "Ahmedabad SVPI Airport"),
    (25.5913, 85.0879,  5_000, 12_000, "Patna Jay Prakash Narayan Airport"),
    (18.5821, 73.9197,  5_000, 12_000, "Pune Airport"),
    (26.7610, 80.8893,  5_000, 12_000, "Lucknow CCS Airport"),
    (21.1804, 81.7388,  5_000, 12_000, "Raipur Swami Vivekananda Airport"),
    (33.9871, 74.7742,  5_000, 12_000, "Srinagar Airport"),
    (34.1359, 77.5465,  5_000, 12_000, "Leh Kushok Bakula Rimpochee Airport"),
    (26.1061, 91.5859,  5_000, 12_000, "Guwahati Lokpriya Gopinath Bordoloi Airport"),
    (24.7600, 93.8967,  5_000, 12_000, "Imphal Bir Tikendrajit Airport"),
    (15.3808, 73.8314,  5_000, 12_000, "Goa Dabolim Airport"),
    (10.1520, 76.4019,  5_000, 12_000, "Cochin International Airport"),
    (11.1368, 75.9553,  5_000, 12_000, "Kozhikode Calicut Airport"),
    (8.4821,  76.9201,  5_000, 12_000, "Thiruvananthapuram Airport"),
    (17.7212, 83.2245,  5_000, 12_000, "Visakhapatnam Airport"),
    (16.5304, 80.7968,  5_000, 12_000, "Vijayawada Airport"),
    (9.8345,  78.0934,  5_000, 12_000, "Madurai Airport"),
    (10.7654, 78.7097,  5_000, 12_000, "Tiruchirappalli Airport"),
    (25.4524, 82.8593,  5_000, 12_000, "Varanasi Lal Bahadur Shastri Airport"),
    (26.4043, 80.4101,  5_000, 12_000, "Kanpur Airport"),
    (28.7077, 77.3589,  5_000, 12_000, "Hindon Airport"),
    (30.6735, 76.7885,  5_000, 12_000, "Chandigarh Airport"),
    (22.7218, 75.8011,  5_000, 12_000, "Indore Devi Ahilya Bai Holkar Airport"),
    (23.1778, 80.0520,  5_000, 12_000, "Jabalpur Airport"),
    (23.2875, 77.3374,  5_000, 12_000, "Bhopal Raja Bhoj Airport"),
]

# (lat, lon, radius_m, name)
SENSITIVE_ZONES: list[tuple[float, float, float, str]] = [
    (28.6143, 77.1999, 3_000, "Central Delhi high-security zone"),
    (18.9420, 72.8430, 3_000, "Mumbai naval dockyard / port zone"),
]


# ══════════════════════════════════════════════════════════════════
# Geometry helpers
# ══════════════════════════════════════════════════════════════════

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points in metres."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _segment_min_distance_m(
    alat: float, alon: float,
    blat: float, blon: float,
    plat: float, plon: float,
) -> float:
    """
    Minimum distance in metres from point P to the line segment A→B.
    Projects everything into a local flat-Earth coordinate system
    centred on the midpoint of AB (accurate enough for segments < 200 km).
    """
    ref_lat = (alat + blat + plat) / 3
    scale_lat = 111_320.0
    scale_lon = 111_320.0 * math.cos(math.radians(ref_lat))

    ax, ay = alon * scale_lon, alat * scale_lat
    bx, by = blon * scale_lon, blat * scale_lat
    px, py = plon * scale_lon, plat * scale_lat

    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq == 0:
        return math.hypot(px - ax, py - ay)

    # Parameter t: projection of P onto the infinite line through A and B
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    closest_x = ax + t * dx
    closest_y = ay + t * dy
    return math.hypot(px - closest_x, py - closest_y)


def _point_in_polygon(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test. Ring is [(lat, lon), ...]."""
    inside = False
    n = len(ring)
    for i in range(n):
        j = (i - 1) % n
        yi, xi = ring[i]
        yj, xj = ring[j]
        if ((yi > lat) != (yj > lat)) and \
                (lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
    return inside


def _geojson_to_ring(geofence: dict) -> Optional[list[tuple[float, float]]]:
    """
    Extract the outer ring from a GeoJSON Polygon as [(lat, lon), ...].
    Skips the closing duplicate vertex.
    Returns None if the geometry is invalid.
    """
    try:
        coords = geofence.get("coordinates", [])
        if not coords or not isinstance(coords[0], list):
            return None
        ring = coords[0]
        # GeoJSON is [lon, lat]; drop the closing repeat
        return [(pt[1], pt[0]) for pt in ring[:-1]]
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════

def check_points(
    points: list[tuple[float, float, str]],
) -> list[AirspaceViolation]:
    """
    Check a list of (lat, lon, label) points against all restricted zones.
    Returns one AirspaceViolation per violation found.
    """
    violations: list[AirspaceViolation] = []
    for lat, lon, label in points:
        for alat, alon, red_m, yellow_m, aname in AIRPORT_ZONES:
            dist = _haversine_m(lat, lon, alat, alon)
            if dist <= red_m:
                violations.append(AirspaceViolation(
                    label=label,
                    zone_name=aname,
                    zone_kind="red",
                    message=(
                        f"{label} is inside the red no-fly zone (0–5 km) of {aname}. "
                        f"Central Government permission required."
                    ),
                ))
            elif dist <= yellow_m:
                violations.append(AirspaceViolation(
                    label=label,
                    zone_name=aname,
                    zone_kind="yellow",
                    message=(
                        f"{label} is inside the controlled yellow zone (5–12 km) of {aname}. "
                        f"ATC / competent authority permission required."
                    ),
                ))
        for slat, slon, radius_m, sname in SENSITIVE_ZONES:
            dist = _haversine_m(lat, lon, slat, slon)
            if dist <= radius_m:
                violations.append(AirspaceViolation(
                    label=label,
                    zone_name=sname,
                    zone_kind="sensitive",
                    message=(
                        f"{label} is inside the restricted zone of {sname}. "
                        f"No-drone operation without Central Government permission."
                    ),
                ))
    return violations


def check_geofence_encloses(
    ring: list[tuple[float, float]],
) -> list[AirspaceViolation]:
    """
    Check whether a geofence polygon (ring of lat/lon pairs) encloses
    the centre of any restricted zone.
    A polygon can legally surround an airport even when no vertex touches it.
    """
    if len(ring) < 3:
        return []

    violations: list[AirspaceViolation] = []
    for alat, alon, _red, _yellow, aname in AIRPORT_ZONES:
        if _point_in_polygon(alat, alon, ring):
            violations.append(AirspaceViolation(
                label="Geofence",
                zone_name=aname,
                zone_kind="red",
                message=(
                    f"Geofence polygon encloses {aname} (restricted airspace). "
                    f"Redraw the geofence to exclude all airport zones."
                ),
            ))
    for slat, slon, _radius, sname in SENSITIVE_ZONES:
        if _point_in_polygon(slat, slon, ring):
            violations.append(AirspaceViolation(
                label="Geofence",
                zone_name=sname,
                zone_kind="sensitive",
                message=(
                    f"Geofence polygon encloses {sname} (restricted area). "
                    f"Redraw the geofence to exclude all restricted zones."
                ),
            ))
    return violations


def check_geofence_edges(
    ring: list[tuple[float, float]],
) -> list[AirspaceViolation]:
    """
    Check whether any edge (line segment between consecutive vertices) of the
    geofence polygon crosses through a restricted zone circle.

    This catches the case where vertices are all outside a zone but the straight
    line between two of them passes through it (e.g. a geofence side clipping
    the edge of an airport red/yellow ring).
    """
    if len(ring) < 2:
        return []

    seen: set[str] = set()   # avoid duplicate violations for the same zone + edge pair
    violations: list[AirspaceViolation] = []
    n = len(ring)

    for i in range(n):
        alat, alon = ring[i]
        blat, blon = ring[(i + 1) % n]
        edge_label = f"Geofence edge {i + 1}–{(i + 1) % n + 1}"

        for zlat, zlon, red_m, yellow_m, zname in AIRPORT_ZONES:
            dist = _segment_min_distance_m(alat, alon, blat, blon, zlat, zlon)
            key_red    = f"{zname}:red:{i}"
            key_yellow = f"{zname}:yellow:{i}"
            if dist <= red_m and key_red not in seen:
                seen.add(key_red)
                violations.append(AirspaceViolation(
                    label=edge_label,
                    zone_name=zname,
                    zone_kind="red",
                    message=(
                        f"{edge_label} crosses through the red no-fly zone (0–5 km) of {zname}. "
                        f"Redraw the geofence to avoid all restricted zones."
                    ),
                ))
            elif dist <= yellow_m and key_yellow not in seen:
                seen.add(key_yellow)
                violations.append(AirspaceViolation(
                    label=edge_label,
                    zone_name=zname,
                    zone_kind="yellow",
                    message=(
                        f"{edge_label} crosses through the controlled yellow zone (5–12 km) of {zname}. "
                        f"Redraw the geofence to avoid all restricted zones."
                    ),
                ))

        for zlat, zlon, radius_m, zname in SENSITIVE_ZONES:
            dist = _segment_min_distance_m(alat, alon, blat, blon, zlat, zlon)
            key = f"{zname}:sensitive:{i}"
            if dist <= radius_m and key not in seen:
                seen.add(key)
                violations.append(AirspaceViolation(
                    label=edge_label,
                    zone_name=zname,
                    zone_kind="sensitive",
                    message=(
                        f"{edge_label} crosses through the restricted zone of {zname}. "
                        f"Redraw the geofence to avoid all restricted zones."
                    ),
                ))

    return violations


def validate_mission_airspace(
    waypoints: list[tuple[float, float, str]],
    geofence: Optional[dict] = None,
) -> AirspaceCheckResult:
    """
    Full airspace check for a mission:
      1. Each waypoint must not be inside a restricted zone.
      2. Each geofence vertex must not be inside a restricted zone.
      3. Each geofence edge must not cross through a restricted zone.
      4. The geofence polygon must not enclose a restricted zone centre.

    Args:
        waypoints: list of (lat, lon, label)
        geofence:  GeoJSON Polygon dict, or None

    Returns:
        AirspaceCheckResult — call .ok, .error_messages
    """
    violations: list[AirspaceViolation] = []

    # 1. Waypoint point checks
    violations.extend(check_points(waypoints))

    if geofence:
        ring = _geojson_to_ring(geofence)
        if ring:
            # 2. Geofence vertex point checks
            vertex_points = [
                (lat, lon, f"Geofence vertex {i + 1}")
                for i, (lat, lon) in enumerate(ring)
            ]
            violations.extend(check_points(vertex_points))

            # 3. Geofence edge intersection checks
            violations.extend(check_geofence_edges(ring))

            # 4. Polygon-encloses-zone-centre check
            violations.extend(check_geofence_encloses(ring))

    return AirspaceCheckResult(violations=violations)
