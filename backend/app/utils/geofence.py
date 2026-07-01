"""
In-memory geofence store.
Maps drone_id → Shapely Polygon built from a GeoJSON Polygon dict.
Callers register a fence via set_geofence(); the TelemetryProcessor
calls is_inside() on every GLOBAL_POSITION_INT message.

GeoJSON coordinate order is [longitude, latitude] — Shapely's x/y.
"""
import json
import structlog
import shapely
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

log = structlog.get_logger()


class GeofenceStore:

    def __init__(self):
        self._fences: dict[int, BaseGeometry] = {}

    def set_geofence(self, drone_id: int, geojson: dict | None) -> bool:
        """
        Register (or clear) a geofence for a drone.
        geojson must be a GeoJSON Polygon or MultiPolygon dict, or None to clear.
        Returns True on success, False if the geometry was invalid.
        """
        if geojson is None:
            self._fences.pop(drone_id, None)
            log.info("Geofence cleared", drone_id=drone_id)
            return True
        try:
            # shapely.from_geojson() is the Shapely 2.x native path and correctly
            # handles all GeoJSON geometry types (Polygon, MultiPolygon, etc.)
            # via the GEOS C layer — unlike shape() which trips on nested lists
            # for collections in Shapely 2.x.
            poly = shapely.from_geojson(json.dumps(geojson))
            if not poly.is_valid:
                poly = poly.buffer(0)
            self._fences[drone_id] = poly
            log.info("Geofence set", drone_id=drone_id, geom_type=poly.geom_type)
            return True
        except Exception as exc:
            log.warning("Invalid geofence GeoJSON — ignored", drone_id=drone_id, error=str(exc))
            return False

    def clear(self, drone_id: int):
        self._fences.pop(drone_id, None)

    def has_fence(self, drone_id: int) -> bool:
        return drone_id in self._fences

    def is_inside(self, drone_id: int, lat: float, lon: float) -> bool | None:
        """
        Returns True if the point is inside the registered fence,
        False if outside, or None if no fence is registered for this drone.
        Shapely Point(x, y) → Point(lon, lat) matches GeoJSON convention.
        """
        poly = self._fences.get(drone_id)
        if poly is None:
            return None
        return poly.contains(Point(lon, lat))


# Module-level singleton — imported by TelemetryProcessor and the drone_flight router
geofence_store = GeofenceStore()
