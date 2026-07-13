import type { GeoPoint } from '@/store/missionStore'

export type ZoneName = 'green' | 'orange' | 'red'

export interface ZoneRule {
  zone: ZoneName
  label: string
  message: string
  maxAltitudeM: number
  maxSpeedMs: number
  recommendedAltitudeM: number
  recommendedSpeedMs: number
}

export interface ZoneLayer {
  zone: ZoneName
  positions: [number, number][]
  color: string
  fillColor: string
  fillOpacity: number
}

function metersPerDegreeLat(lat: number) {
  return 111_320 * Math.cos((lat * Math.PI) / 180)
}

function approxDistanceMeters(lat1: number, lon1: number, lat2: number, lon2: number) {
  const dLat = (lat2 - lat1) * 111_320
  const dLon = (lon2 - lon1) * metersPerDegreeLat((lat1 + lat2) / 2)
  return Math.sqrt(dLat * dLat + dLon * dLon)
}

export function pointInPolygon(lat: number, lon: number, points: GeoPoint[] | null | undefined) {
  if (!points || points.length < 3) return true

  let inside = false
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const xi = points[i].lng
    const yi = points[i].lat
    const xj = points[j].lng
    const yj = points[j].lat
    const intersects = ((yi > lat) !== (yj > lat)) &&
      (lon < ((xj - xi) * (lat - yi)) / ((yj - yi) || 1e-12) + xi)
    if (intersects) inside = !inside
  }
  return inside
}

function distanceToSegmentMeters(lat: number, lon: number, a: GeoPoint, b: GeoPoint) {
  const refLat = (lat + a.lat + b.lat) / 3
  const x = lon * metersPerDegreeLat(refLat)
  const y = lat * 111_320
  const ax = a.lng * metersPerDegreeLat(refLat)
  const ay = a.lat * 111_320
  const bx = b.lng * metersPerDegreeLat(refLat)
  const by = b.lat * 111_320
  const dx = bx - ax
  const dy = by - ay
  const lenSq = dx * dx + dy * dy
  if (lenSq === 0) return Math.hypot(x - ax, y - ay)
  const t = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / lenSq))
  return Math.hypot(x - (ax + t * dx), y - (ay + t * dy))
}

function distanceToBoundaryMeters(lat: number, lon: number, points: GeoPoint[]) {
  let min = Number.POSITIVE_INFINITY
  for (let i = 0; i < points.length; i += 1) {
    const next = (i + 1) % points.length
    min = Math.min(min, distanceToSegmentMeters(lat, lon, points[i], points[next]))
  }
  return min
}

export function getZoneRule(lat: number, lon: number, geofence: GeoPoint[] | null | undefined): ZoneRule {
  if (!geofence || geofence.length < 3) {
    return {
      zone: 'green',
      label: 'Green corridor',
      message: 'Normal transit corridor. Maintain standard altitude and speed.',
      maxAltitudeM: 50,
      maxSpeedMs: 12,
      recommendedAltitudeM: 30,
      recommendedSpeedMs: 8,
    }
  }

  const centerLat = geofence.reduce((sum, p) => sum + p.lat, 0) / geofence.length
  const centerLon = geofence.reduce((sum, p) => sum + p.lng, 0) / geofence.length
  const radiusMeters = Math.max(...geofence.map(p => approxDistanceMeters(centerLat, centerLon, p.lat, p.lng)))
  const inside = pointInPolygon(lat, lon, geofence)

  if (!inside) {
    return {
      zone: 'red',
      label: 'Outside geofence',
      message: 'Restricted boundary crossed. Auto-RTL should hold the aircraft inside the approved area.',
      maxAltitudeM: 18,
      maxSpeedMs: 4,
      recommendedAltitudeM: 12,
      recommendedSpeedMs: 3,
    }
  }

  const boundaryDistance = distanceToBoundaryMeters(lat, lon, geofence)
  const cautionBandMeters = Math.max(10, radiusMeters * 0.15)

  if (boundaryDistance > cautionBandMeters) {
    return {
      zone: 'green',
      label: 'Inside geofence',
      message: 'Transit is inside the approved geofence.',
      maxAltitudeM: 50,
      maxSpeedMs: 12,
      recommendedAltitudeM: 30,
      recommendedSpeedMs: 8,
    }
  }

  return {
    zone: 'orange',
    label: 'Geofence edge caution',
    message: 'Approaching the geofence edge. Reduce speed and be ready to hold or return.',
    maxAltitudeM: 35,
    maxSpeedMs: 8,
    recommendedAltitudeM: 20,
    recommendedSpeedMs: 5,
  }
}

export function buildZoneLayers(lat: number, lon: number, geofence: GeoPoint[] | null | undefined): ZoneLayer[] {
  if (geofence && geofence.length >= 3) {
    return [{
      zone: 'green',
      positions: geofence.map(p => [p.lat, p.lng] as [number, number]),
      color: '#0f766e',
      fillColor: '#14b8a6',
      fillOpacity: 0.12,
    }]
  }

  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return []
  return []
}
