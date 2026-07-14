// ═══════════════════════════════════════════════════════════════
// src/utils/geofence.ts
// Point-in-polygon test + GeoJSON parsing, shared by anything that
// needs to check a live position against a mission's geofence.
// ═══════════════════════════════════════════════════════════════

export interface GeoPoint { lat: number; lng: number }

/** Ray-casting point-in-polygon test. No geofence (<3 points) is treated as "inside". */
export function isPointInsidePolygon(point: GeoPoint, polygon: GeoPoint[]): boolean {
  if (polygon.length < 3) return true
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i].lng, yi = polygon[i].lat
    const xj = polygon[j].lng, yj = polygon[j].lat
    const intersects = ((yi > point.lat) !== (yj > point.lat)) &&
      (point.lng < ((xj - xi) * (point.lat - yi)) / (yj - yi || 1e-12) + xi)
    if (intersects) inside = !inside
  }
  return inside
}

/** Converts a stored GeoJSON Polygon (mission.geofence) into a plain point list. */
export function geoJsonToPolygon(geofence: any): GeoPoint[] {
  const ring = geofence?.coordinates?.[0]
  if (!Array.isArray(ring)) return []
  return ring
    .slice(0, ring.length > 1 ? -1 : ring.length)
    .map((p: number[]) => ({ lng: Number(p[0]), lat: Number(p[1]) }))
    .filter((p: GeoPoint) => Number.isFinite(p.lat) && Number.isFinite(p.lng))
}
