"""
Geospatial Utilities
====================
Shared geographic computation helpers used across drone_flight,
drone_control, and drone_analyst.

Distinct from drone_flight/geo_service.py which contains
mission-specific business logic (battery estimates, mission summaries).
This module is pure geometry — no domain models, no database calls.
"""
import math
from typing import Optional
from pyproj import Geod, Transformer

# WGS84 geodetic calculator — used for accurate great-circle operations
_GEOD = Geod(ellps="WGS84")

# EPSG:4326 (WGS84 lat/lon) ↔ EPSG:3857 (Web Mercator, metres)
_TO_MERCATOR   = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
_FROM_MERCATOR = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)


# ══════════════════════════════════════════════════════════════════
# Distance and bearing
# ══════════════════════════════════════════════════════════════════

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance between two WGS84 points in metres.
    Uses pyproj for accuracy (accounts for Earth's ellipsoidal shape).
    """
    _, _, dist = _GEOD.inv(lon1, lat1, lon2, lat2)
    return abs(dist)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return haversine_m(lat1, lon1, lat2, lon2) / 1000.0


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Initial bearing from point 1 → point 2 in degrees (0–360, 0 = North).
    """
    fwd_az, _, _ = _GEOD.inv(lon1, lat1, lon2, lat2)
    return (fwd_az + 360) % 360


def destination_point(
    lat: float, lon: float,
    bearing: float, distance_m: float,
) -> tuple[float, float]:
    """
    Returns the (lat, lon) reached by travelling `distance_m`
    metres from (lat, lon) on the given bearing.
    """
    lon2, lat2, _ = _GEOD.fwd(lon, lat, bearing, distance_m)
    return lat2, lon2


def midpoint(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> tuple[float, float]:
    """Geographic midpoint between two coordinates."""
    mid_dist = haversine_m(lat1, lon1, lat2, lon2) / 2.0
    brg      = bearing_deg(lat1, lon1, lat2, lon2)
    return destination_point(lat1, lon1, brg, mid_dist)


# ══════════════════════════════════════════════════════════════════
# Bounding box
# ══════════════════════════════════════════════════════════════════

def bounding_box(
    points: list[tuple[float, float]]
) -> tuple[float, float, float, float]:
    """
    Returns (min_lat, min_lon, max_lat, max_lon) for a list of (lat, lon).
    """
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return min(lats), min(lons), max(lats), max(lons)


def bbox_centre(
    min_lat: float, min_lon: float,
    max_lat: float, max_lon: float,
) -> tuple[float, float]:
    return (min_lat + max_lat) / 2.0, (min_lon + max_lon) / 2.0


def bbox_area_km2(
    min_lat: float, min_lon: float,
    max_lat: float, max_lon: float,
) -> float:
    """Approximate bounding box area in km² (flat-earth, good for < 100 km)."""
    height_m = haversine_m(min_lat, min_lon, max_lat, min_lon)
    width_m  = haversine_m(min_lat, min_lon, min_lat, max_lon)
    return (height_m * width_m) / 1e6


# ══════════════════════════════════════════════════════════════════
# Point-in-polygon
# ══════════════════════════════════════════════════════════════════

def point_in_polygon(
    lat: float, lon: float,
    polygon: list[tuple[float, float]],
) -> bool:
    """
    Ray-casting algorithm.
    polygon is a list of (lat, lon) tuples forming a closed ring.
    Returns True if (lat, lon) is inside the polygon.
    """
    n       = len(polygon)
    inside  = False
    j       = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > lon) != (yj > lon)) and \
                (lat < (xj - xi) * (lon - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def geojson_polygon_to_ring(
    geojson: dict,
) -> Optional[list[tuple[float, float]]]:
    """
    Extracts the outer ring from a GeoJSON Polygon as (lat, lon) tuples.
    Returns None if the structure is invalid.
    """
    try:
        coords = geojson["coordinates"][0]   # outer ring
        return [(c[1], c[0]) for c in coords]  # GeoJSON is [lon,lat], we want (lat,lon)
    except (KeyError, IndexError, TypeError):
        return None


def all_points_in_geofence(
    points: list[tuple[float, float]],
    geofence: dict,
) -> tuple[bool, list[int]]:
    """
    Checks all (lat, lon) points against a GeoJSON polygon geofence.
    Returns (all_inside: bool, violating_indices: list[int]).
    """
    ring = geojson_polygon_to_ring(geofence)
    if ring is None:
        return True, []   # Can't validate — treat as pass

    violations = [
        i for i, (lat, lon) in enumerate(points)
        if not point_in_polygon(lat, lon, ring)
    ]
    return len(violations) == 0, violations


# ══════════════════════════════════════════════════════════════════
# Coordinate format conversion
# ══════════════════════════════════════════════════════════════════

def dd_to_dms(
    decimal_degrees: float,
    is_latitude: bool = True,
) -> str:
    """
    Converts decimal degrees to Degrees Minutes Seconds string.
    e.g. 17.385277  →  "17° 23' 6.997\" N"
    """
    direction = ""
    if is_latitude:
        direction = "N" if decimal_degrees >= 0 else "S"
    else:
        direction = "E" if decimal_degrees >= 0 else "W"

    dd = abs(decimal_degrees)
    degrees = int(dd)
    minutes = int((dd - degrees) * 60)
    seconds = ((dd - degrees) * 60 - minutes) * 60

    return f"{degrees}° {minutes}' {seconds:.3f}\" {direction}"


def dms_to_dd(degrees: float, minutes: float, seconds: float, direction: str) -> float:
    """
    Converts Degrees Minutes Seconds to decimal degrees.
    direction: 'N', 'S', 'E', 'W'
    """
    dd = degrees + minutes / 60.0 + seconds / 3600.0
    if direction.upper() in ("S", "W"):
        dd = -dd
    return dd


def latlon_to_mercator(lat: float, lon: float) -> tuple[float, float]:
    """Convert WGS84 lat/lon to Web Mercator (EPSG:3857) x, y in metres."""
    x, y = _TO_MERCATOR.transform(lon, lat)
    return x, y


def mercator_to_latlon(x: float, y: float) -> tuple[float, float]:
    """Convert Web Mercator (EPSG:3857) x, y to WGS84 lat/lon."""
    lon, lat = _FROM_MERCATOR.transform(x, y)
    return lat, lon


# ══════════════════════════════════════════════════════════════════
# Terrain and altitude helpers
# ══════════════════════════════════════════════════════════════════

def agl_to_msl(alt_agl: float, ground_elevation_m: float) -> float:
    """Convert altitude Above Ground Level to Mean Sea Level."""
    return alt_agl + ground_elevation_m


def msl_to_agl(alt_msl: float, ground_elevation_m: float) -> float:
    """Convert altitude Mean Sea Level to Above Ground Level."""
    return max(0.0, alt_msl - ground_elevation_m)


def line_of_sight_distance(
    alt1_m: float, alt2_m: float,
    earth_radius_m: float = 6_371_000,
    k_factor: float = 4 / 3,
) -> float:
    """
    Approximate radio line-of-sight distance in metres between
    two points at given altitudes, accounting for atmospheric
    refraction via the 4/3 Earth radius k-factor.

    Useful for estimating maximum communication range.
    """
    r = earth_radius_m * k_factor
    return math.sqrt(2 * r * alt1_m) + math.sqrt(2 * r * alt2_m)


# ══════════════════════════════════════════════════════════════════
# Path and polygon helpers
# ══════════════════════════════════════════════════════════════════

def total_path_distance_m(
    waypoints: list[tuple[float, float]]
) -> float:
    """
    Total 2D great-circle path distance through an ordered list
    of (lat, lon) waypoints in metres.
    """
    if len(waypoints) < 2:
        return 0.0
    return sum(
        haversine_m(waypoints[i][0], waypoints[i][1],
                    waypoints[i + 1][0], waypoints[i + 1][1])
        for i in range(len(waypoints) - 1)
    )


def polygon_area_m2(polygon: list[tuple[float, float]]) -> float:
    """
    Approximate area of a lat/lon polygon in square metres
    using the Shoelace formula in Mercator projection.
    Accurate for polygons < ~500 km².
    """
    if len(polygon) < 3:
        return 0.0
    # Project to Mercator for metric area calculation
    pts = [latlon_to_mercator(lat, lon) for lat, lon in polygon]
    n   = len(pts)
    area = 0.0
    j    = n - 1
    for i in range(n):
        area += (pts[j][0] + pts[i][0]) * (pts[j][1] - pts[i][1])
        j = i
    return abs(area / 2.0)


def simplify_path(
    waypoints: list[tuple[float, float]],
    tolerance_m: float = 5.0,
) -> list[tuple[float, float]]:
    """
    Ramer-Douglas-Peucker path simplification.
    Removes intermediate waypoints that deviate less than
    `tolerance_m` metres from the straight-line segment.
    Useful for compressing dense GPS tracks before storage.
    """
    if len(waypoints) <= 2:
        return waypoints

    def _perp_distance(point, line_start, line_end):
        if line_start == line_end:
            return haversine_m(*point, *line_start)
        lat0, lon0 = point
        lat1, lon1 = line_start
        lat2, lon2 = line_end
        # Cross-track distance formula (flat-earth approximation)
        d13 = haversine_m(lat1, lon1, lat0, lon0)
        b13 = math.radians(bearing_deg(lat1, lon1, lat0, lon0))
        b12 = math.radians(bearing_deg(lat1, lon1, lat2, lon2))
        r   = 6_371_000
        return abs(math.asin(math.sin(d13 / r) * math.sin(b13 - b12)) * r)

    def _rdp(points, eps):
        if len(points) < 3:
            return points
        dmax  = 0.0
        index = 0
        for i in range(1, len(points) - 1):
            d = _perp_distance(points[i], points[0], points[-1])
            if d > dmax:
                dmax  = d
                index = i
        if dmax > eps:
            left  = _rdp(points[:index + 1], eps)
            right = _rdp(points[index:],     eps)
            return left[:-1] + right
        return [points[0], points[-1]]

    return _rdp(waypoints, tolerance_m)
    