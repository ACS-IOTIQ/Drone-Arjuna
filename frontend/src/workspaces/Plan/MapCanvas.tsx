import { useEffect, useMemo, useState } from 'react'
import { LayersControl, LayerGroup, MapContainer, Marker, Polygon, Polyline, Popup, TileLayer, Tooltip, useMapEvents, ZoomControl } from 'react-leaflet'
import L, { type LeafletEvent } from 'leaflet'
import { CheckCircle2, Cpu, Eye, Pencil, PlusCircle, Route, Shield, Trash2 } from 'lucide-react'
import { useMissionStore, type GeoPoint } from '@/store/missionStore'
import { useFleetStore } from '@/store/fleetStore'
import { useTelemetryStore } from '@/store/telemetryStore'
import { droneFlightApi } from '@/api/droneFlight'
import { notify } from '@/store/notificationStore'
import { buildZoneLayers } from '@/utils/geofenceZones'
import { buildRegulatoryZoneLayers, getRegulatoryRule, regulatoryZones } from '@/utils/regulatoryZones'

const FLEET_COLORS = ['#2563eb', '#dc2626', '#16a34a', '#d97706', '#7c3aed', '#0891b2', '#db2777', '#65a30d']

function colorForDrone(droneId: number | null | undefined) {
  if (droneId == null) return '#64748b'
  return FLEET_COLORS[droneId % FLEET_COLORS.length]
}

function geofenceRingToLatLng(geofence: any): [number, number][] {
  const ring = geofence?.coordinates?.[0]
  if (!Array.isArray(ring)) return []
  return ring
    .map((p: number[]) => [Number(p[1]), Number(p[0])] as [number, number])
    .filter(p => Number.isFinite(p[0]) && Number.isFinite(p[1]))
}

function wpIcon(seq: number, isHome: boolean, outside: boolean) {
  const bg = outside ? '#dc2626' : isHome ? '#16a34a' : '#2563eb'
  const border = outside ? '#991b1b' : isHome ? '#15803d' : '#1d4ed8'
  return L.divIcon({
    className: '',
    iconSize: [30, 30],
    iconAnchor: [15, 15],
    html: `<div style="
      width:30px; height:30px; border-radius:50%;
      background:${bg};
      border:2px solid ${border};
      display:flex; align-items:center; justify-content:center;
      color:white; font-size:11px; font-weight:700;
      box-shadow:0 2px 8px rgba(15,23,42,0.35);
    ">${outside ? '!' : isHome ? 'H' : seq}</div>`,
  })
}

function liveDroneIcon(heading: number, callSign?: string) {
  const size = 32
  return L.divIcon({
    className: '',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: `<div style="position:relative; width:${size}px; height:${size}px;">
      <div style="
        width:${size}px; height:${size}px;
        display:flex; align-items:center; justify-content:center;
        transform: rotate(${heading}deg);
      ">
        <svg viewBox="0 0 24 24" width="${size - 6}" height="${size - 6}">
          <polygon points="12,2 7,22 12,18 17,22" fill="#3b82f6" stroke="#1d4ed8" stroke-width="1"/>
        </svg>
      </div>
      ${callSign ? `<div style="
        position:absolute; top:100%; left:50%; transform:translateX(-50%);
        white-space:nowrap; font-size:9px; font-weight:700; color:#1d4ed8;
        background:rgba(255,255,255,0.9); padding:0 3px; border-radius:2px;
      ">${callSign}</div>` : ''}
    </div>`,
  })
}

function vertexIcon(idx: number) {
  return L.divIcon({
    className: '',
    iconSize: [20, 20],
    iconAnchor: [10, 10],
    html: `<div style="
      width:20px; height:20px; border-radius:50%;
      background:#ffffff; border:3px solid #0f766e;
      display:flex; align-items:center; justify-content:center;
      color:#0f766e; font-size:9px; font-weight:800;
      box-shadow:0 1px 6px rgba(15,23,42,0.25);
    ">${idx + 1}</div>`,
  })
}

function isPointInsidePolygon(point: GeoPoint, polygon: GeoPoint[]) {
  if (polygon.length < 3) return true
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i].lng
    const yi = polygon[i].lat
    const xj = polygon[j].lng
    const yj = polygon[j].lat
    const intersects = ((yi > point.lat) !== (yj > point.lat)) &&
      (point.lng < ((xj - xi) * (point.lat - yi)) / (yj - yi || 1e-12) + xi)
    if (intersects) inside = !inside
  }
  return inside
}

function segmentMinDistanceM(
  aLat: number, aLng: number,
  bLat: number, bLng: number,
  pLat: number, pLng: number,
): number {
  const refLat = (aLat + bLat + pLat) / 3
  const scaleLat = 111_320
  const scaleLon = 111_320 * Math.cos((refLat * Math.PI) / 180)
  const ax = aLng * scaleLon, ay = aLat * scaleLat
  const bx = bLng * scaleLon, by = bLat * scaleLat
  const px = pLng * scaleLon, py = pLat * scaleLat
  const dx = bx - ax, dy = by - ay
  const lenSq = dx * dx + dy * dy
  if (lenSq === 0) return Math.hypot(px - ax, py - ay)
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lenSq))
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy))
}

function edgeCrossesRestrictedZone(prev: GeoPoint, next: GeoPoint): string | null {
  for (const zone of regulatoryZones) {
    if (!zone.center) continue
    const [zLat, zLon] = zone.center
    // Use the outer radius of the zone as the threshold
    const radius = (zone as any).outerRadiusM ?? 12_000
    const dist = segmentMinDistanceM(prev.lat, prev.lng, next.lat, next.lng, zLat, zLon)
    if (dist <= radius) return zone.name
  }
  return null
}

function geofenceEnclosesRestrictedZone(pts: GeoPoint[]): string | null {
  if (pts.length < 3) return null
  for (const zone of regulatoryZones) {
    if (!zone.center) continue
    const [zLat, zLon] = zone.center
    if (isPointInsidePolygon({ lat: zLat, lng: zLon }, pts)) {
      return zone.name
    }
  }
  return null
}

function validateGovernmentPlacement(lat: number, lng: number, target: 'waypoint' | 'geofence vertex') {
  const rule = getRegulatoryRule(lat, lng, 0)
  if (!rule) return true

  if (rule.kind === 'red') {
    notify.danger(
      'Placement blocked — restricted airspace',
      `Cannot place ${target} inside ${rule.name}. ${rule.restriction}`,
    )
    return false
  }

  if (rule.kind === 'orange') {
    notify.danger(
      'Placement blocked — controlled airspace',
      `Cannot place ${target} inside ${rule.name}. ${rule.restriction} ATC/authority permission required.`,
    )
    return false
  }

  return true
}

function MapClickHandler({ drawing, routeDrawing }: { drawing: boolean; routeDrawing: boolean }) {
  const { draftWaypoints, addWaypoint, geofence, setGeofence } = useMissionStore()
  useMapEvents({
    click(e) {
      if (drawing) {
        const newPt = { lat: e.latlng.lat, lng: e.latlng.lng }
        // 1. Vertex itself inside a restricted zone
        if (!validateGovernmentPlacement(newPt.lat, newPt.lng, 'geofence vertex')) return
        // 2. Edge from the previous vertex to this one crosses a restricted zone
        if (geofence.length > 0) {
          const prev = geofence[geofence.length - 1]
          const crossedZone = edgeCrossesRestrictedZone(prev, newPt)
          if (crossedZone) {
            notify.danger(
              'Geofence edge crosses restricted airspace',
              `The line from vertex ${geofence.length} to the new point crosses ${crossedZone}. Redraw to avoid all restricted zones.`,
            )
            setGeofence([])
            return
          }
        }
        const nextGeofence = [...geofence, newPt]
        // 3. Closing edge (last vertex back to first) would cross a zone
        if (nextGeofence.length >= 3) {
          const closingZone = edgeCrossesRestrictedZone(newPt, nextGeofence[0])
          if (closingZone) {
            notify.danger(
              'Geofence closing edge crosses restricted airspace',
              `The closing edge of this polygon crosses ${closingZone}. Redraw to avoid all restricted zones.`,
            )
            setGeofence([])
            return
          }
          // 4. Polygon encloses a zone centre
          const enclosed = geofenceEnclosesRestrictedZone(nextGeofence)
          if (enclosed) {
            notify.danger(
              'Geofence encloses restricted airspace',
              `This polygon encloses ${enclosed}. Clear the geofence and redraw to exclude all restricted zones.`,
            )
            setGeofence([])
            return
          }
        }
        setGeofence(nextGeofence)
        return
      }

      if (!routeDrawing) return
      const newWp = { lat: e.latlng.lat, lng: e.latlng.lng }

      // 1. New waypoint itself inside a restricted zone
      const rule = getRegulatoryRule(newWp.lat, newWp.lng, 100)
      if (rule && (rule.kind === 'red' || rule.kind === 'orange')) {
        notify.danger(
          rule.kind === 'red' ? 'Waypoint blocked — restricted airspace' : 'Waypoint blocked — controlled airspace',
          `Cannot place waypoint inside ${rule.name}. ${rule.restriction}`,
        )
        return
      }

      // 2. Flight line from previous waypoint to this one crosses a restricted zone
      if (draftWaypoints.length > 0) {
        const prev = draftWaypoints[draftWaypoints.length - 1]
        const prevPt = { lat: prev.latitude, lng: prev.longitude }
        const crossedZone = edgeCrossesRestrictedZone(prevPt, newWp)
        if (crossedZone) {
          notify.danger(
            'Flight path crosses restricted airspace',
            `The line from waypoint ${draftWaypoints.length} to the new point crosses ${crossedZone}. Place waypoints to avoid restricted zones.`,
          )
          return
        }
      }

      // 3. Waypoints placed so far (including this one) surround/enclose a restricted zone
      const routePts = [...draftWaypoints.map(w => ({ lat: w.latitude, lng: w.longitude })), newWp]
      if (routePts.length >= 3) {
        const enclosedZone = geofenceEnclosesRestrictedZone(routePts)
        if (enclosedZone) {
          notify.danger(
            'Flight path surrounds restricted airspace',
            `These waypoints surround ${enclosedZone}. Place waypoints so the route does not enclose restricted zones.`,
          )
          return
        }
      }

      const seq = draftWaypoints.length + 1
      addWaypoint({
        sequence: seq,
        latitude: e.latlng.lat,
        longitude: e.latlng.lng,
        altitude_m: 100,
        altitude_ref: 'AGL',
        action: 'none',
        is_home: seq === 1,
      })
    },
  })
  return null
}

type MapCanvasProps = {
  onFleetAssign?: () => void
}

export default function MapCanvas({ onFleetAssign }: MapCanvasProps) {
  const {
    draftWaypoints,
    geofence,
    removeWaypoint,
    updateGeofencePoint,
    clearGeofence,
    clearDraft,
    setGeofence,
    activeMissionId,
    missions,
  } = useMissionStore()
  const instances = useFleetStore(s => s.instances)
  const [drawing, setDrawing] = useState(false)
  const [routeDrawing, setRouteDrawing] = useState(true)
  const [manualLat, setManualLat] = useState('')
  const [manualLng, setManualLng] = useState('')
  const [showAllMissions, setShowAllMissions] = useState(false)

  const droneName = (id: number | null | undefined) =>
    instances.find(i => i.id === id)?.call_sign ?? (id != null ? `Drone #${id}` : 'Unassigned')

  const activeMission = useMemo(
    () => missions.find(m => m.id === activeMissionId),
    [missions, activeMissionId],
  )
  const liveDroneId = activeMission?.drone_instance_id ?? null
  const liveFrame = useTelemetryStore(s => (liveDroneId != null ? s.frames[liveDroneId] : null))
  const hasLivePosition = Boolean(liveFrame && (liveFrame.lat !== 0 || liveFrame.lon !== 0))

  // While the operator draws/drags waypoints, mirror the draft route straight
  // to the drone over its live MAVLink link (UDP for SITL) — debounced so
  // dragging a vertex doesn't flood the link with a re-upload every frame.
  const connections = useFleetStore(s => s.connections)
  const isMavlinkConnected = liveDroneId != null
    && connections[liveDroneId]?.connected
    && connections[liveDroneId]?.transport !== 'simulation'

  useEffect(() => {
    if (!isMavlinkConnected || liveDroneId == null || draftWaypoints.length === 0) return
    const handle = setTimeout(() => {
      droneFlightApi
        .liveSyncWaypoints(liveDroneId, draftWaypoints, geofence.length >= 3 ? { geofence } : null)
        .catch((err: any) => {
          notify.danger(
            'Live waypoint sync failed',
            err?.response?.data?.detail || err?.message || 'Could not push waypoints to the drone',
          )
        })
    }, 500)
    return () => clearTimeout(handle)
  }, [draftWaypoints, geofence, isMavlinkConnected, liveDroneId])

  const otherMissions = useMemo(
    () => missions.filter(m => m.id !== activeMissionId && (m.waypoints?.length || m.geofence)),
    [missions, activeMissionId],
  )

  const routePositions = draftWaypoints.map(w => [w.latitude, w.longitude] as [number, number])
  const geofencePositions = geofence.map(p => [p.lat, p.lng] as [number, number])
  const zoneLayers = useMemo(() => {
    if (geofence.length < 3) return []
    const centerLat = geofence.reduce((sum, p) => sum + p.lat, 0) / geofence.length
    const centerLng = geofence.reduce((sum, p) => sum + p.lng, 0) / geofence.length
    return buildZoneLayers(centerLat, centerLng, geofence)
  }, [geofence])
  const regulatoryZoneLayers = useMemo(() => buildRegulatoryZoneLayers(), [])
  useEffect(() => {
    if (activeMissionId && draftWaypoints.length > 0) setRouteDrawing(false)
  }, [activeMissionId, draftWaypoints.length])
  const outsideCount = useMemo(
    () => draftWaypoints.filter(w => !isPointInsidePolygon({ lat: w.latitude, lng: w.longitude }, geofence)).length,
    [draftWaypoints, geofence],
  )

  const startDrawing = () => {
    clearGeofence()
    setRouteDrawing(false)
    setDrawing(true)
  }

  const finishDrawing = () => {
    if (geofence.length < 3) return
    // Check all edges (including closing edge) for zone intersection
    for (let i = 0; i < geofence.length; i++) {
      const a = geofence[i]
      const b = geofence[(i + 1) % geofence.length]
      const crossedZone = edgeCrossesRestrictedZone(a, b)
      if (crossedZone) {
        notify.danger(
          'Geofence crosses restricted airspace',
          `Geofence edge ${i + 1} crosses ${crossedZone}. Redraw to avoid all restricted zones.`,
        )
        clearGeofence()
        return
      }
    }
    const enclosedZone = geofenceEnclosesRestrictedZone(geofence)
    if (enclosedZone) {
      notify.danger(
        'Geofence encloses restricted airspace',
        `Your geofence contains ${enclosedZone}. Redraw it to exclude all restricted zones.`,
      )
      clearGeofence()
      return
    }
    setDrawing(false)
  }

  const deleteZone = () => {
    clearGeofence()
    setDrawing(false)
  }

  const startRoute = () => {
    setDrawing(false)
    setRouteDrawing(true)
  }

  const completeRoute = () => {
    if (draftWaypoints.length > 0) setRouteDrawing(false)
  }

  const addManualVertex = () => {
    const lat = Number(manualLat)
    const lng = Number(manualLng)
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return
    if (!validateGovernmentPlacement(lat, lng, 'geofence vertex')) return
    const newPt = { lat, lng }
    if (geofence.length > 0) {
      const crossedZone = edgeCrossesRestrictedZone(geofence[geofence.length - 1], newPt)
      if (crossedZone) {
        notify.danger('Geofence edge crosses restricted airspace', `Edge crosses ${crossedZone}. Adjust coordinates.`)
        return
      }
    }
    setGeofence([...geofence, newPt])
    setManualLat('')
    setManualLng('')
  }

  const removeVertex = (idx: number) => {
    setGeofence(geofence.filter((_, i) => i !== idx))
  }

  const clearMission = () => {
    clearDraft()
    setDrawing(false)
    setRouteDrawing(true)
  }

  return (
    <div className="relative h-full w-full">
      <MapContainer
        center={[17.385, 78.4867]}
        zoom={13}
        style={{ height: '100%', width: '100%' }}
        zoomControl={false}>

        <ZoomControl position="bottomright" />

        {/* Geofence drawn BEFORE regulatory zones so restrictions render on top */}
        {geofencePositions.length > 1 && (
          <Polygon
            positions={geofencePositions}
            pathOptions={{
              color: '#0f766e',
              weight: 3,
              fillColor: '#14b8a6',
              fillOpacity: 0.10,
              dashArray: drawing ? '8 6' : undefined,
            }} />
        )}

        {positionsForLine(geofencePositions, drawing).length > 1 && drawing && (
          <Polyline positions={positionsForLine(geofencePositions, drawing)}
            pathOptions={{ color: '#0f766e', weight: 2, dashArray: '4 4', opacity: 0.9 }} />
        )}

        <LayersControl position="topright">
          <LayersControl.BaseLayer checked name="OpenStreetMap">
            <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="© OpenStreetMap" />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="OpenTopoMap">
            <TileLayer url="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png" attribution="© OpenTopoMap" />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Carto Light">
            <TileLayer url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png" attribution="© CARTO" />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Esri Satellite">
            <TileLayer url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}" attribution="© Esri" />
          </LayersControl.BaseLayer>

          <LayersControl.Overlay checked name="Drone zone guidance">
            <LayerGroup>
              {zoneLayers.map(layer => (
                <Polygon
                  key={layer.zone}
                  positions={layer.positions}
                  pathOptions={{ color: layer.color, fillColor: layer.fillColor, fillOpacity: layer.fillOpacity, weight: 1.4 }}
                />
              ))}
            </LayerGroup>
          </LayersControl.Overlay>
          <LayersControl.Overlay checked name="Government airspace zones">
            <LayerGroup>
              {regulatoryZoneLayers.map(layer => (
                <Polygon
                  key={layer.id}
                  positions={layer.positions}
                  pathOptions={{ color: layer.color, fillColor: layer.fillColor, fillOpacity: layer.fillOpacity, weight: 1.2 }}>
                  <Popup>
                    <div style={{ padding: 6, minWidth: 180 }}>
                      <div style={{ fontWeight: 700 }}>{layer.name}</div>
                      <div style={{ fontSize: 11, color: '#475569' }}>{layer.restriction}</div>
                      <div style={{ fontSize: 11, color: '#92400e', marginTop: 4 }}>
                        Limit: {layer.maxAltitudeM} m / {layer.maxSpeedMs} m/s
                      </div>
                    </div>
                  </Popup>
                </Polygon>
              ))}
            </LayerGroup>
          </LayersControl.Overlay>
        </LayersControl>

        {showAllMissions && (
          <LayerGroup>
            {otherMissions.map(m => {
              const color = colorForDrone(m.drone_instance_id)
              const route = (m.waypoints ?? [])
                .slice()
                .sort((a, b) => a.sequence - b.sequence)
                .map(w => [w.latitude, w.longitude] as [number, number])
              const fence = geofenceRingToLatLng(m.geofence)
              return (
                <LayerGroup key={m.id}>
                  {route.length > 1 && (
                    <Polyline positions={route} pathOptions={{ color, weight: 2.5, opacity: 0.75, dashArray: '2 6' }}>
                      <Popup>
                        <div style={{ padding: 4, minWidth: 160 }}>
                          <div style={{ fontWeight: 700 }}>{m.name}</div>
                          <div style={{ fontSize: 11, color: '#475569' }}>{droneName(m.drone_instance_id)} · {m.status}</div>
                        </div>
                      </Popup>
                    </Polyline>
                  )}
                  {fence.length > 1 && (
                    <Polygon positions={fence} pathOptions={{ color, weight: 1.5, fillColor: color, fillOpacity: 0.06, dashArray: '2 6' }}>
                      <Popup>
                        <div style={{ padding: 4, minWidth: 160 }}>
                          <div style={{ fontWeight: 700 }}>{m.name} — geofence</div>
                          <div style={{ fontSize: 11, color: '#475569' }}>{droneName(m.drone_instance_id)}</div>
                        </div>
                      </Popup>
                    </Polygon>
                  )}
                </LayerGroup>
              )
            })}
          </LayerGroup>
        )}

        {geofence.map((point, idx) => (
          <Marker
            key={`vertex-${idx}`}
            position={[point.lat, point.lng]}
            icon={vertexIcon(idx)}
            draggable
            eventHandlers={{
              dragend: (event: LeafletEvent) => {
                const marker = event.target as L.Marker
                const next = marker.getLatLng()
                const newPt = { lat: next.lat, lng: next.lng }
                const n = geofence.length

                // 1. Vertex itself inside a restricted zone
                if (!validateGovernmentPlacement(newPt.lat, newPt.lng, 'geofence vertex')) {
                  marker.setLatLng([point.lat, point.lng])
                  return
                }

                // 2. Check both adjacent edges (prev→new and new→next)
                const prevPt = geofence[(idx - 1 + n) % n]
                const nextPt = geofence[(idx + 1) % n]
                const crossPrev = n > 1 ? edgeCrossesRestrictedZone(prevPt, newPt) : null
                const crossNext = n > 1 ? edgeCrossesRestrictedZone(newPt, nextPt) : null
                const crossed = crossPrev ?? crossNext
                if (crossed) {
                  notify.danger(
                    'Geofence edge crosses restricted airspace',
                    `Dragging vertex ${idx + 1} here causes an edge to cross ${crossed}. Move it away from restricted zones.`,
                  )
                  marker.setLatLng([point.lat, point.lng])
                  return
                }

                // 3. Check if updated polygon encloses a zone centre
                const updated = geofence.map((p, i) => i === idx ? newPt : p)
                const enclosed = geofenceEnclosesRestrictedZone(updated)
                if (enclosed) {
                  notify.danger(
                    'Geofence encloses restricted airspace',
                    `This position causes the geofence to enclose ${enclosed}. Move the vertex away.`,
                  )
                  marker.setLatLng([point.lat, point.lng])
                  return
                }

                updateGeofencePoint(idx, newPt)
              },
            }}>
            <Popup>Geofence vertex {idx + 1}</Popup>
          </Marker>
        ))}

        {routePositions.length > 1 && (
          <Polyline positions={routePositions}
            pathOptions={{ color: '#2563eb', weight: 3, dashArray: '6 4', opacity: 0.85 }} />
        )}

        {draftWaypoints.map(wp => {
          const outside = !isPointInsidePolygon({ lat: wp.latitude, lng: wp.longitude }, geofence)
          return (
            <Marker
              key={wp.sequence}
              position={[wp.latitude, wp.longitude]}
              icon={wpIcon(wp.sequence, !!wp.is_home, outside)}>
              <Popup>
                <div style={{ padding: 8, minWidth: 170 }}>
                  <div style={{ fontWeight: 700, marginBottom: 4, color: outside ? '#dc2626' : '#0f172a' }}>
                    {outside ? 'Outside Geofence' : wp.is_home ? 'Home / Takeoff' : `Waypoint ${wp.sequence}`}
                  </div>
                  <div style={{ fontSize: 11, color: '#475569' }}>
                    {wp.latitude.toFixed(5)}, {wp.longitude.toFixed(5)}
                  </div>
                  <div style={{ fontSize: 11, color: '#475569' }}>
                    Alt: {wp.altitude_m} m {wp.altitude_ref}
                  </div>
                  <button
                    onClick={() => removeWaypoint(wp.sequence)}
                    style={{
                      marginTop: 8, width: '100%', padding: '5px 0',
                      background: '#fee2e2', color: '#b91c1c',
                      border: '1px solid #fecaca', borderRadius: 4,
                      fontSize: 11, cursor: 'pointer',
                    }}>
                    Remove waypoint
                  </button>
                </div>
              </Popup>
            </Marker>
          )
        })}

        {hasLivePosition && liveFrame && (
          <Marker
            position={[liveFrame.lat, liveFrame.lon]}
            icon={liveDroneIcon(liveFrame.heading ?? 0, droneName(liveDroneId))}
            zIndexOffset={1000}>
            <Tooltip direction="top" offset={[0, -16]}>
              {droneName(liveDroneId)} · {liveFrame.flight_mode} · {Math.round(liveFrame.alt_agl ?? 0)} m AGL
            </Tooltip>
          </Marker>
        )}

        <MapClickHandler drawing={drawing} routeDrawing={routeDrawing} />
      </MapContainer>

      <div className="absolute top-3 left-3 right-3 z-[999] flex flex-wrap items-start gap-2 pointer-events-none">
        <div className="da-card p-2 flex flex-col gap-2 pointer-events-auto">
          <div className="flex items-center gap-2">
            <button onClick={startRoute} disabled={routeDrawing && !drawing} className="da-btn da-btn-ghost">
              <Route size={14} /> Plot Route
            </button>
            <button onClick={completeRoute} disabled={!routeDrawing || draftWaypoints.length === 0} className="da-btn da-btn-primary">
              <CheckCircle2 size={14} /> Complete Path
            </button>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={startDrawing} className="da-btn da-btn-teal">
              <Pencil size={14} /> Draw Geofence
            </button>
            <button onClick={finishDrawing} disabled={!drawing || geofence.length < 3} className="da-btn da-btn-primary">
              <Shield size={14} /> Finish
            </button>
            <button onClick={deleteZone} disabled={geofence.length === 0} className="da-btn da-btn-ghost">
              <Trash2 size={14} /> Delete
            </button>
          </div>
          <div className="flex items-center gap-2">
            <input
              value={manualLat}
              onChange={e => setManualLat(e.target.value)}
              placeholder="Lat"
              className="w-24 rounded border border-slate-300 px-2 py-1 text-xs"
            />
            <input
              value={manualLng}
              onChange={e => setManualLng(e.target.value)}
              placeholder="Lng"
              className="w-24 rounded border border-slate-300 px-2 py-1 text-xs"
            />
            <button onClick={addManualVertex} className="da-btn da-btn-ghost" style={{ padding: '4px 8px' }}>
              <PlusCircle size={14} /> Add
            </button>
          </div>
          <span className="text-xs mono px-2" style={{ color: outsideCount > 0 ? '#dc2626' : '#0f766e' }}>
            {routeDrawing ? 'Route plotting active' : 'Route plotting complete'} - {geofence.length < 3 ? `${geofence.length}/3 vertices` : `${outsideCount} outside`}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowAllMissions(v => !v)}
              className={showAllMissions ? 'da-btn da-btn-teal' : 'da-btn da-btn-ghost'}>
              <Eye size={14} /> {showAllMissions ? 'Hide other drones' : 'Show all drone missions'}
            </button>
          </div>
          {showAllMissions && otherMissions.length > 0 && (
            <div className="max-h-28 overflow-auto rounded border border-slate-200 bg-white/90 p-2 text-[11px] text-slate-600">
              {otherMissions.map(m => (
                <div key={m.id} className="mb-1 flex items-center gap-2">
                  <span
                    style={{
                      display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
                      background: colorForDrone(m.drone_instance_id), flexShrink: 0,
                    }}
                  />
                  <span className="truncate">{droneName(m.drone_instance_id)} — {m.name} ({m.status})</span>
                </div>
              ))}
            </div>
          )}
          {showAllMissions && otherMissions.length === 0 && (
            <span className="text-[11px] px-2" style={{ color: '#64748b' }}>No other drone missions with waypoints/geofence yet.</span>
          )}
          {geofence.length > 0 && (
            <div className="max-h-32 overflow-auto rounded border border-slate-200 bg-white/90 p-2 text-[11px] text-slate-600">
              {geofence.map((point, idx) => (
                <div key={`${idx}-${point.lat}-${point.lng}`} className="mb-1 flex items-center justify-between gap-2">
                  <span>#{idx + 1} {point.lat.toFixed(5)}, {point.lng.toFixed(5)}</span>
                  <button onClick={() => removeVertex(idx)} className="text-red-500" title="Remove point">
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {onFleetAssign && (
          <button className="da-btn da-btn-teal shrink-0 pointer-events-auto" onClick={onFleetAssign}>
            <Cpu size={14} /> Fleet Assign
          </button>
        )}
      </div>

      {draftWaypoints.length === 0 && !drawing && routeDrawing && (
        <div className="absolute bottom-24 left-1/2 -translate-x-1/2 z-[999] px-4 py-2 rounded-full text-xs"
          style={{ background: 'rgba(255,255,255,0.94)', color: '#334155', border: '1px solid var(--da-border)' }}>
          Click the map to place waypoints
        </div>
      )}

      {draftWaypoints.length > 0 && !drawing && !routeDrawing && (
        <div className="absolute bottom-24 left-1/2 -translate-x-1/2 z-[999] px-4 py-2 rounded-full text-xs"
          style={{ background: 'rgba(240,253,244,0.96)', color: '#166534', border: '1px solid #bbf7d0' }}>
          Path complete. Use Plot Route to add more waypoints.
        </div>
      )}

      {drawing && (
        <div className="absolute bottom-24 left-1/2 -translate-x-1/2 z-[999] px-4 py-2 rounded-full text-xs"
          style={{ background: '#ecfeff', color: '#0f766e', border: '1px solid #99f6e4' }}>
          Click at least 3 points, drag vertices to adjust, then finish the geofence
        </div>
      )}

      {(draftWaypoints.length > 0 || geofence.length > 0) && (
        <div className="absolute bottom-6 right-3 z-[999]">
          <button onClick={clearMission} className="da-btn da-btn-ghost" style={{ background: 'rgba(255,255,255,0.94)' }}>
            <Trash2 size={14} /> Clear mission
          </button>
        </div>
      )}

      <div className="absolute bottom-6 left-3 z-[999] max-w-[260px] rounded px-3 py-2 text-[11px] leading-snug pointer-events-none"
        style={{ background: 'rgba(255,255,255,0.94)', color: '#475569', border: '1px solid var(--da-border)' }}>
        <span style={{ fontWeight: 700, color: '#92400e' }}>Government airspace zones</span> are fixed real-world
        restricted-airspace rings (airports etc.) — they do not move with your waypoints or geofence. Only the
        teal geofence outline reflects what you draw.
      </div>
    </div>
  )
}

function positionsForLine(positions: [number, number][], drawing: boolean) {
  if (!drawing || positions.length < 3) return positions
  return [...positions, positions[0]]
}
