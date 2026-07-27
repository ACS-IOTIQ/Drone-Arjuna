export interface LatLngPoint {
  lat: number
  lng: number
}

export interface RouteCollision {
  id: string
  lat: number
  lng: number
  distanceM: number
  routeALegIndex: number
  routeBLegIndex: number
}

interface XYPoint {
  x: number
  y: number
}

const METERS_PER_DEGREE_LAT = 111_320

function scaleLon(refLat: number) {
  return METERS_PER_DEGREE_LAT * Math.cos((refLat * Math.PI) / 180)
}

function project(point: LatLngPoint, refLat: number): XYPoint {
  return {
    x: point.lng * scaleLon(refLat),
    y: point.lat * METERS_PER_DEGREE_LAT,
  }
}

function unproject(point: XYPoint, refLat: number): LatLngPoint {
  return {
    lat: point.y / METERS_PER_DEGREE_LAT,
    lng: point.x / scaleLon(refLat),
  }
}

function pointOnSegment(point: XYPoint, a: XYPoint, b: XYPoint) {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const lenSq = dx * dx + dy * dy
  if (lenSq === 0) return { point: a, distance: Math.hypot(point.x - a.x, point.y - a.y) }

  const t = Math.max(0, Math.min(1, ((point.x - a.x) * dx + (point.y - a.y) * dy) / lenSq))
  const closest = { x: a.x + t * dx, y: a.y + t * dy }
  return { point: closest, distance: Math.hypot(point.x - closest.x, point.y - closest.y) }
}

function segmentIntersection(a: XYPoint, b: XYPoint, c: XYPoint, d: XYPoint): XYPoint | null {
  const den = (a.x - b.x) * (c.y - d.y) - (a.y - b.y) * (c.x - d.x)
  if (Math.abs(den) < 1e-9) return null

  const detA = a.x * b.y - a.y * b.x
  const detB = c.x * d.y - c.y * d.x
  const x = (detA * (c.x - d.x) - (a.x - b.x) * detB) / den
  const y = (detA * (c.y - d.y) - (a.y - b.y) * detB) / den
  const eps = 1e-6
  const within = (v: number, start: number, end: number) =>
    v >= Math.min(start, end) - eps && v <= Math.max(start, end) + eps

  if (
    within(x, a.x, b.x) && within(y, a.y, b.y) &&
    within(x, c.x, d.x) && within(y, c.y, d.y)
  ) {
    return { x, y }
  }

  return null
}

function closestSegmentPoint(a: XYPoint, b: XYPoint, c: XYPoint, d: XYPoint) {
  const candidates = [
    { source: a, target: pointOnSegment(a, c, d) },
    { source: b, target: pointOnSegment(b, c, d) },
    { source: c, target: pointOnSegment(c, a, b) },
    { source: d, target: pointOnSegment(d, a, b) },
  ]
  const best = candidates.reduce((min, next) => next.target.distance < min.target.distance ? next : min)
  return {
    point: {
      x: (best.source.x + best.target.point.x) / 2,
      y: (best.source.y + best.target.point.y) / 2,
    },
    distance: best.target.distance,
  }
}

function isDuplicate(collision: RouteCollision, collisions: RouteCollision[], thresholdM: number) {
  const refLat = collision.lat
  const next = project(collision, refLat)
  return collisions.some(existing => {
    const prev = project(existing, refLat)
    return Math.hypot(next.x - prev.x, next.y - prev.y) <= Math.max(5, thresholdM / 2)
  })
}

export function findRouteCollisions(
  routeA: LatLngPoint[],
  routeB: LatLngPoint[],
  thresholdM = 20,
): RouteCollision[] {
  if (routeA.length < 2 || routeB.length < 2) return []

  const collisions: RouteCollision[] = []

  for (let i = 0; i < routeA.length - 1; i++) {
    const a = routeA[i]
    const b = routeA[i + 1]
    if (!Number.isFinite(a.lat) || !Number.isFinite(a.lng) || !Number.isFinite(b.lat) || !Number.isFinite(b.lng)) continue

    for (let j = 0; j < routeB.length - 1; j++) {
      const c = routeB[j]
      const d = routeB[j + 1]
      if (!Number.isFinite(c.lat) || !Number.isFinite(c.lng) || !Number.isFinite(d.lat) || !Number.isFinite(d.lng)) continue

      const refLat = (a.lat + b.lat + c.lat + d.lat) / 4
      const pa = project(a, refLat)
      const pb = project(b, refLat)
      const pc = project(c, refLat)
      const pd = project(d, refLat)
      const crossing = segmentIntersection(pa, pb, pc, pd)
      const closest = crossing ? { point: crossing, distance: 0 } : closestSegmentPoint(pa, pb, pc, pd)

      if (closest.distance <= thresholdM) {
        const point = unproject(closest.point, refLat)
        const collision: RouteCollision = {
          id: `${i}:${j}:${point.lat.toFixed(6)}:${point.lng.toFixed(6)}`,
          lat: point.lat,
          lng: point.lng,
          distanceM: closest.distance,
          routeALegIndex: i,
          routeBLegIndex: j,
        }
        if (!isDuplicate(collision, collisions, thresholdM)) collisions.push(collision)
      }
    }
  }

  return collisions
}

export function formatCollisionCoord(point: LatLngPoint) {
  return `Lon ${point.lng.toFixed(6)}, Lat ${point.lat.toFixed(6)}`
}
