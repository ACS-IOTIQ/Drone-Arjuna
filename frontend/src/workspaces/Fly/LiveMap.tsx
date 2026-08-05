import { useEffect, useMemo, useRef, useState } from 'react'
import { LayersControl, LayerGroup, MapContainer, Marker, Polygon, Polyline, Popup, TileLayer, Tooltip, useMap, ZoomControl } from 'react-leaflet'
import L from 'leaflet'
import { droneControlApi } from '@/api/droneControl'
import { useMissionStore, type GeoPoint } from '@/store/missionStore'
import type { WaypointInput } from '@/api/droneFlight'
import { notify } from '@/store/notificationStore'
import { useTelemetryStore } from '@/store/telemetryStore'
import { useFleetStore } from '@/store/fleetStore'
import { useVesselStore } from '@/store/vesselStore'
import { buildZoneLayers, getZoneRule } from '@/utils/geofenceZones'
import {
  buildRegulatoryZoneLayers,
  getRegulatoryRule,
  loadDgcaRegulatoryZones,
  subscribeRegulatoryZoneUpdates,
} from '@/utils/regulatoryZones'
import { findRouteCollisions, formatCollisionCoord, type LatLngPoint } from '@/utils/routeCollision'
import { AlertTriangle, ShieldAlert, X } from 'lucide-react'

const FLEET_COLORS = ['#2563eb', '#dc2626', '#16a34a', '#d97706', '#7c3aed', '#0891b2', '#db2777', '#65a30d']

function colorForDrone(droneId: number | null | undefined) {
  if (droneId == null) return '#64748b'
  return FLEET_COLORS[droneId % FLEET_COLORS.length]
}

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[char] ?? char))
}

function droneIcon(heading: number, active: boolean, callSign?: string) {
  const size   = active ? 38 : 30
  const boxW   = active ? 70 : 62
  const boxH   = size + 20
  const fill   = active ? '#3b82f6' : '#94a3b8'
  const stroke = active ? '#1d4ed8' : '#64748b'
  const label = callSign ? escapeHtml(callSign) : ''
  return L.divIcon({
    className: '',
    iconSize: [boxW, boxH],
    iconAnchor: [boxW / 2, size / 2],
    html: `<div style="position:relative; width:${boxW}px; height:${boxH}px;">
      <div style="
        position:absolute; left:50%; top:0; margin-left:${-size / 2}px;
        width:${size}px; height:${size}px;
        display:flex; align-items:center; justify-content:center;
        transform: rotate(${heading}deg);
        opacity:${active ? 1 : 0.85};
      ">
        <svg viewBox="0 0 48 48" width="${size}" height="${size}">
          <line x1="14" y1="14" x2="34" y2="34" stroke="${stroke}" stroke-width="3" stroke-linecap="round"/>
          <line x1="34" y1="14" x2="14" y2="34" stroke="${stroke}" stroke-width="3" stroke-linecap="round"/>
          <circle cx="11" cy="11" r="7" fill="rgba(255,255,255,0.92)" stroke="${stroke}" stroke-width="2"/>
          <circle cx="37" cy="11" r="7" fill="rgba(255,255,255,0.92)" stroke="${stroke}" stroke-width="2"/>
          <circle cx="11" cy="37" r="7" fill="rgba(255,255,255,0.92)" stroke="${stroke}" stroke-width="2"/>
          <circle cx="37" cy="37" r="7" fill="rgba(255,255,255,0.92)" stroke="${stroke}" stroke-width="2"/>
          <ellipse cx="24" cy="24" rx="9" ry="12" fill="${fill}" stroke="${stroke}" stroke-width="2"/>
          <path d="M24 10 L29 22 L19 22 Z" fill="#ffffff" fill-opacity="0.9"/>
          <circle cx="24" cy="27" r="2.4" fill="#0f172a" fill-opacity="0.55"/>
        </svg>
      </div>
      ${label ? `<div style="
        position:absolute; top:${size}px; left:50%; transform:translateX(-50%);
        max-width:${boxW}px; overflow:hidden; text-overflow:ellipsis;
        white-space:nowrap; font-size:9px; font-weight:700; color:#0f172a;
        background:rgba(255,255,255,0.9); padding:0 4px; border-radius:3px;
        border:1px solid rgba(148,163,184,0.45);
      ">${label}</div>` : ''}
    </div>`,
  })
}

function vesselIcon(heading: number) {
  return L.divIcon({
    className: '',
    iconSize: [40, 40],
    iconAnchor: [20, 20],
    html: `<div style="
      width:40px; height:40px;
      display:flex; align-items:center; justify-content:center;
      transform: rotate(${heading}deg);
    ">
      <svg viewBox="0 0 24 24" width="32" height="32">
        <path d="M12 2 L17 8 L17 17 L12 20 L7 17 L7 8 Z"
              fill="#06b6d4" fill-opacity="0.85" stroke="#0891b2" stroke-width="1.2"/>
        <line x1="12" y1="2" x2="12" y2="5" stroke="#ffffff" stroke-width="1.5"/>
      </svg>
    </div>`,
  })
}

function simWaypointIcon(seq: number) {
  const size = 16
  return L.divIcon({
    className: '',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: `<div style="
      width:${size}px; height:${size}px; border-radius:50%;
      background:#ffffff;
      border:2px solid #2563eb;
      display:flex; align-items:center; justify-content:center;
      color:#1d4ed8; font-size:7px; font-weight:800;
      box-shadow:0 1px 4px rgba(15,23,42,0.20);
    ">${seq}</div>`,
  })
}

function collisionIcon(idx: number) {
  const size = 30
  return L.divIcon({
    className: '',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: `<div style="
      width:${size}px; height:${size}px; border-radius:50%;
      background:#f97316;
      border:2px solid #7c2d12;
      display:flex; align-items:center; justify-content:center;
      color:#ffffff; font-size:11px; font-weight:900;
      box-shadow:0 0 0 3px rgba(249,115,22,0.20), 0 2px 8px rgba(15,23,42,0.34);
    ">${idx}</div>`,
  })
}

function normalizeGeofence(geofence: any): GeoPoint[] | null {
  if (!geofence) return null
  if (Array.isArray(geofence)) return geofence.filter(Boolean) as GeoPoint[]

  const ring = geofence?.coordinates?.[0] ?? geofence?.geometry?.coordinates?.[0]
  if (!Array.isArray(ring)) return null

  return ring
    .slice(0, ring.length > 1 ? -1 : ring.length)
    .map((p: number[]) => ({ lat: Number(p[1]), lng: Number(p[0]) }))
    .filter(p => Number.isFinite(p.lat) && Number.isFinite(p.lng))
}

function MapFollower({ lat, lon }: { lat: number; lon: number }) {
  const map = useMap()
  const firstRef = useRef(true)

  useEffect(() => {
    if (lat === 0 && lon === 0) return
    if (firstRef.current) {
      map.setView([lat, lon], 15)
      firstRef.current = false
    } else {
      map.panTo([lat, lon], { animate: true, duration: 0.8 })
    }
  }, [lat, lon, map])

  return null
}

function MapResizeHandler() {
  const map = useMap()

  useEffect(() => {
    const container = map.getContainer()
    const observer = new ResizeObserver(() => map.invalidateSize({ animate: false }))
    observer.observe(container)
    const frame = requestAnimationFrame(() => map.invalidateSize({ animate: false }))
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [map])

  return null
}

interface Props {
  droneId: number | null
  onSelectDrone?: (droneId: number) => void
  onManualControlRequest?: () => void
}

export default function LiveMap({ droneId, onSelectDrone, onManualControlRequest }: Props) {
  const frames  = useTelemetryStore(s => s.frames)
  const frame   = droneId ? frames[droneId] : null
  const history = useTelemetryStore(s => droneId ? s.history[droneId] : [])
  const instances = useFleetStore(s => s.instances)
  const vessels = useVesselStore(s => s.vessels)
  const missions = useMissionStore(s => s.missions)
  const fetchMissions = useMissionStore(s => s.fetchMissions)
  const missionGeofence = useMissionStore(s => s.geofence)
  const [runtimeGeofence, setRuntimeGeofence] = useState<any | null>(null)
  const [activeDetail, setActiveDetail] = useState<'airspace' | 'collisions' | null>(null)
  const [regulatoryZoneVersion, setRegulatoryZoneVersion] = useState(0)
  const lastRegulatoryRef = useRef<string | null>(null)
  const lastComplianceRef = useRef<string | null>(null)
  const liveCollisionNoticeKeyRef = useRef('')
  const autoActionRef = useRef<Map<string, number>>(new Map())

  // Breadcrumb trail — every 5th frame, only for the active/followed drone
  const trail = (history ?? [])
    .filter((_, i) => i % 5 === 0)
    .map(f => [f.lat, f.lon] as [number, number])
    .filter(([lat, lon]) => lat !== 0 || lon !== 0)

  useEffect(() => {
    const unsubscribe = subscribeRegulatoryZoneUpdates(() => setRegulatoryZoneVersion(version => version + 1))
    loadDgcaRegulatoryZones().finally(() => setRegulatoryZoneVersion(version => version + 1))
    return unsubscribe
  }, [])

  useEffect(() => {
    const hasSimFrame = Object.values(frames).some(f => f?.sim_phase)
    if (hasSimFrame && missions.length === 0) {
      fetchMissions()
    }
  }, [frames, missions.length, fetchMissions])

  useEffect(() => {
    if (!droneId) {
      setRuntimeGeofence(null)
      return
    }
    let ignore = false
    droneControlApi.getGeofence(droneId)
      .then(({ data }) => {
        if (!ignore) setRuntimeGeofence(data?.geofence ?? null)
      })
      .catch(() => {
        if (!ignore) setRuntimeGeofence(null)
      })
    return () => { ignore = true }
  }, [droneId])

  const displayGeofence = useMemo(
    () => normalizeGeofence(runtimeGeofence) ?? missionGeofence ?? null,
    [runtimeGeofence, missionGeofence],
  )
  const hasPosition = Boolean(frame && (frame.lat !== 0 || frame.lon !== 0))
  const simMission = useMemo(() => {
    if (!frame?.sim_phase) return null
    if (frame.mission_id != null) {
      return missions.find(m => m.id === frame.mission_id) ?? null
    }
    if (droneId != null) {
      return missions.find(m => m.drone_instance_id === droneId) ?? null
    }
    return null
  }, [frame?.sim_phase, frame?.mission_id, missions, droneId])
  const simWaypoints = useMemo<WaypointInput[]>(() => (
    (simMission?.waypoints ?? [])
      .filter(w => !w.is_home)
      .filter(w => Number.isFinite(w.latitude) && Number.isFinite(w.longitude))
      .slice()
      .sort((a, b) => a.sequence - b.sequence)
  ), [simMission])
  const zoneRule = useMemo(() => {
    if (!frame) return null
    return getZoneRule(frame.lat, frame.lon, displayGeofence)
  }, [frame, displayGeofence])
  const zoneLayers = useMemo(() => {
    const lat = frame?.lat ?? 0
    const lon = frame?.lon ?? 0
    return buildZoneLayers(lat, lon, displayGeofence)
  }, [frame, displayGeofence])
  const regulatoryZones = useMemo(() => buildRegulatoryZoneLayers(), [regulatoryZoneVersion])
  const currentRegulatoryZone = useMemo(() => {
    if (!frame) return null
    return getRegulatoryRule(frame.lat, frame.lon, frame.alt_agl ?? 0)
  }, [frame, regulatoryZoneVersion])

  const droneName = (id: number, callSign?: string) =>
    callSign ?? instances.find(i => i.id === id)?.call_sign ?? `Drone #${id}`

  const simDroneRoutes = useMemo(() => (
    Object.entries(frames)
      .map(([id, f]) => ({ id: Number(id), frame: f }))
      .filter(({ frame: f }) => f?.sim_phase && (f.lat !== 0 || f.lon !== 0))
      .map(({ id, frame: f }) => {
        const mission = f.mission_id != null
          ? missions.find(m => m.id === f.mission_id)
          : missions.find(m => m.drone_instance_id === id)
        const route = (mission?.waypoints ?? [])
          .filter(w => !w.is_home)
          .filter(w => Number.isFinite(w.latitude) && Number.isFinite(w.longitude))
          .slice()
          .sort((a, b) => a.sequence - b.sequence)
          .map(w => ({ lat: w.latitude, lng: w.longitude } as LatLngPoint))
        return { droneId: id, callSign: f.call_sign, mission, route }
      })
      .filter(item => item.route.length > 1)
  ), [frames, missions])

  const liveRouteCollisions = useMemo(() => {
    const collisions: Array<ReturnType<typeof findRouteCollisions>[number] & {
      droneAId: number
      droneBId: number
      droneAName: string
      droneBName: string
      missionAName: string
      missionBName: string
    }> = []

    for (let i = 0; i < simDroneRoutes.length - 1; i++) {
      for (let j = i + 1; j < simDroneRoutes.length; j++) {
        const a = simDroneRoutes[i]
        const b = simDroneRoutes[j]
        collisions.push(...findRouteCollisions(a.route, b.route).map(collision => ({
          ...collision,
          droneAId: a.droneId,
          droneBId: b.droneId,
          droneAName: droneName(a.droneId, a.callSign),
          droneBName: droneName(b.droneId, b.callSign),
          missionAName: a.mission?.name ?? 'simulation route',
          missionBName: b.mission?.name ?? 'simulation route',
        })))
      }
    }

    return collisions
  }, [simDroneRoutes, instances])

  const activeCompliance = useMemo(() => {
    if (!frame || !zoneRule) return null
    const maxAltitudeM = Math.min(
      zoneRule.maxAltitudeM,
      currentRegulatoryZone?.maxAltitudeM ?? Number.POSITIVE_INFINITY,
    )
    const maxSpeedMs = Math.min(
      zoneRule.maxSpeedMs,
      currentRegulatoryZone?.maxSpeedMs ?? Number.POSITIVE_INFINITY,
    )
    const altitudeExceeded = frame.alt_agl > maxAltitudeM
    const speedExceeded = frame.groundspeed_ms > maxSpeedMs
    const geofenceExceeded = zoneRule.zone === 'red' || Boolean(frame.geofence_breach)
    return {
      maxAltitudeM,
      maxSpeedMs,
      altitudeExceeded,
      speedExceeded,
      geofenceExceeded,
      hasViolation: altitudeExceeded || speedExceeded || geofenceExceeded,
    }
  }, [frame, zoneRule, currentRegulatoryZone])

  useEffect(() => {
    if (!droneId || !frame || !activeCompliance) return
    const violations = [
      activeCompliance.geofenceExceeded ? 'geofence' : '',
      activeCompliance.altitudeExceeded ? 'altitude' : '',
      activeCompliance.speedExceeded ? 'speed' : '',
    ].filter(Boolean)
    const key = violations.join(':')
    if (!key || lastComplianceRef.current === key) {
      if (!key) lastComplianceRef.current = null
      return
    }
    lastComplianceRef.current = key
    notify.warning(
      'Live restriction limit exceeded',
      `Drone ${droneId}: ${violations.join(', ')} limit active. Alt ${frame.alt_agl.toFixed(1)} / ${activeCompliance.maxAltitudeM} m, speed ${frame.groundspeed_ms.toFixed(1)} / ${activeCompliance.maxSpeedMs} m/s.`,
      droneId,
    )
  }, [droneId, frame, activeCompliance])

  useEffect(() => {
    if (!droneId || !frame || !currentRegulatoryZone) return

    const zoneKey = `${currentRegulatoryZone.id}:${currentRegulatoryZone.action}`
    if (lastRegulatoryRef.current !== zoneKey) {
      lastRegulatoryRef.current = zoneKey
      const message = `${currentRegulatoryZone.name}. ${currentRegulatoryZone.restriction}`
      if (currentRegulatoryZone.kind === 'red') {
        notify.danger('Red government airspace entered', message, droneId)
      } else if (currentRegulatoryZone.kind === 'orange') {
        notify.warning('Orange government airspace entered', message, droneId)
      } else {
        notify.info('Government green zone', message, droneId)
      }
    }

    if (currentRegulatoryZone.action === 'continue') return

    const now = Date.now()
    const lastActionAt = autoActionRef.current.get(zoneKey) ?? 0
    if (now - lastActionAt < 15_000) return

    const runAutoAction = async () => {
      try {
        if (currentRegulatoryZone.action === 'rtl') {
          await droneControlApi.command({ drone_id: droneId, command: 'rtl' })
          autoActionRef.current.set(zoneKey, Date.now())
          notify.danger(
            'Automatic RTL sent',
            `Drone ${droneId} entered ${currentRegulatoryZone.name}. RTL was sent for no-drone zone protection.`,
            droneId,
          )
          return
        }

        if (currentRegulatoryZone.action === 'hold') {
          await droneControlApi.command({ drone_id: droneId, command: 'set_mode', params: { mode: 'LOITER' } })
          autoActionRef.current.set(zoneKey, Date.now())
          notify.warning(
            'Automatic hold sent',
            `Drone ${droneId} entered ${currentRegulatoryZone.name}. LOITER was requested pending clearance.`,
            droneId,
          )
          return
        }

        if (frame.alt_agl > currentRegulatoryZone.maxAltitudeM) {
          const targetAlt = Math.max(0, currentRegulatoryZone.recommendedAltitudeM || currentRegulatoryZone.maxAltitudeM)
          await droneControlApi.command({
            drone_id: droneId,
            command: 'goto',
            params: { latitude: frame.lat, longitude: frame.lon, altitude_m: targetAlt },
          })
          autoActionRef.current.set(zoneKey, Date.now())
          notify.warning(
            'Altitude adjustment sent',
            `Drone ${droneId} was above the ${currentRegulatoryZone.maxAltitudeM} m limit. Target altitude set to ${targetAlt} m.`,
            droneId,
          )
        }
      } catch {
        notify.danger(
          'Automatic airspace adjustment failed',
          `Drone ${droneId} needs operator review for ${currentRegulatoryZone.name}. The app will retry while the violation remains active.`,
          droneId,
        )
      }
    }

    runAutoAction()
  }, [droneId, frame, currentRegulatoryZone])

  useEffect(() => {
    if (liveRouteCollisions.length === 0) {
      liveCollisionNoticeKeyRef.current = ''
      return
    }

    const key = liveRouteCollisions
      .map(c => `${c.droneAId}:${c.droneBId}:${c.id}`)
      .sort()
      .join('|')
    if (liveCollisionNoticeKeyRef.current === key) return

    liveCollisionNoticeKeyRef.current = key
    const pairs = Array.from(new Set(liveRouteCollisions.map(c => `${c.droneAName} and ${c.droneBName}`))).join(', ')
    const coords = liveRouteCollisions.slice(0, 3).map(c => formatCollisionCoord(c)).join('; ')
    const suffix = liveRouteCollisions.length > 3 ? `; +${liveRouteCollisions.length - 3} more` : ''
    notify.warning(
      'Simulation path collision warning',
      `${pairs} have ${liveRouteCollisions.length} path collision point(s): ${coords}${suffix}.`,
    )
  }, [liveRouteCollisions])

  useEffect(() => {
    if (activeDetail === 'collisions' && liveRouteCollisions.length === 0) {
      setActiveDetail(null)
    }
    if (activeDetail === 'airspace' && (!frame || !zoneRule)) {
      setActiveDetail(null)
    }
  }, [activeDetail, liveRouteCollisions.length, frame, zoneRule])

  // Only actively-simulated drones with a known position — rendered simultaneously
  const allDrones = Object.entries(frames)
    .map(([id, f]) => ({ id: Number(id), frame: f }))
    .filter(({ frame: f }) => f && f.sim_phase && (f.lat !== 0 || f.lon !== 0))

  // Vessels with known positions
  const positionedVessels = vessels.filter(v => v.latitude != null && v.longitude != null)

  return (
    <div className={activeDetail ? 'da-live-map-shell detail-open' : 'da-live-map-shell'}>
      <div className="da-live-map-stage">
        <MapContainer
      center={[17.385, 78.4867]}
      zoom={15}
      minZoom={3}
      maxZoom={18}
      scrollWheelZoom
      doubleClickZoom
      touchZoom
      boxZoom
      keyboard
      zoomAnimation
      style={{ height: '100%', width: '100%' }}
      zoomControl={false}>
      <MapResizeHandler />
      <ZoomControl
        position="bottomright"
        zoomInTitle="Zoom in"
        zoomOutTitle="Zoom out"
      />
      <LayersControl position="bottomleft">
        <LayersControl.BaseLayer checked name="OpenStreetMap">
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="© OpenStreetMap" />
        </LayersControl.BaseLayer>
        <LayersControl.BaseLayer name="OpenTopoMap">
          <TileLayer url="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png" attribution="© OpenTopoMap" />
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
                pathOptions={{ color: layer.color, fillColor: layer.fillColor, fillOpacity: layer.fillOpacity, weight: 2 }}
              />
            ))}
          </LayerGroup>
        </LayersControl.Overlay>

        <LayersControl.Overlay checked name="Government airspace zones">
          <LayerGroup>
            {regulatoryZones.map(layer => (
              <Polygon
                key={layer.id}
                positions={layer.positions}
                pathOptions={{ color: layer.color, fillColor: layer.fillColor, fillOpacity: layer.fillOpacity, weight: 1.8 }}>
                <Tooltip sticky>
                  <div style={{ fontSize: 11, maxWidth: 220 }}>
                    <strong>{layer.name}</strong>
                    <div>{layer.restriction}</div>
                    <div>Limit: {layer.maxAltitudeM} m / {layer.maxSpeedMs} m/s</div>
                  </div>
                </Tooltip>
              </Polygon>
            ))}
          </LayerGroup>
        </LayersControl.Overlay>
      </LayersControl>

      {hasPosition && <MapFollower lat={frame!.lat} lon={frame!.lon} />}
      {trail.length > 1 && (
        <Polyline
          positions={trail}
          pathOptions={{ color: '#3b82f6', weight: 1.5, opacity: 0.5 }} />
      )}

      {simDroneRoutes.map(route => (
        <Polyline
          key={`sim-route-${route.droneId}`}
          positions={route.route.map(p => [p.lat, p.lng] as [number, number])}
          pathOptions={{
            color: colorForDrone(route.droneId),
            weight: route.droneId === droneId ? 2.8 : 2,
            opacity: route.droneId === droneId ? 0.82 : 0.58,
            dashArray: route.droneId === droneId ? '4 6' : '2 7',
          }} />
      ))}

      {simWaypoints.map(wp => (
        <Marker
          key={`sim-wp-${wp.sequence}`}
          position={[wp.latitude, wp.longitude]}
          icon={simWaypointIcon(wp.sequence)}
          interactive={false} />
      ))}

      {liveRouteCollisions.map((collision, idx) => (
        <Marker
          key={`live-route-collision-${collision.droneAId}-${collision.droneBId}-${collision.id}`}
          position={[collision.lat, collision.lng]}
          icon={collisionIcon(idx + 1)}>
          <Tooltip direction="top" offset={[0, -14]}>
            <div style={{ fontSize: 11, minWidth: 210 }}>
              <strong>Collision point {idx + 1}</strong>
              <div>{formatCollisionCoord(collision)}</div>
              <div style={{ color: '#475569', marginTop: 2 }}>
                {collision.droneAName} / {collision.missionAName}
              </div>
              <div style={{ color: '#475569' }}>
                {collision.droneBName} / {collision.missionBName}
              </div>
              <div style={{ color: '#475569' }}>
                Separation {collision.distanceM.toFixed(1)} m
              </div>
            </div>
          </Tooltip>
        </Marker>
      ))}

      {allDrones.map(({ id, frame: f }) => (
        id === droneId && frame ? (
          <Marker
            key={`drone-${id}`}
            position={[f.lat, f.lon]}
            icon={droneIcon(f.heading, true, f.call_sign)}
            eventHandlers={onSelectDrone ? { click: () => onSelectDrone(id) } : undefined}>
            <Tooltip direction="top" offset={[0, -16]}>
              <div style={{ fontSize: 11, minWidth: 140 }}>
                <div style={{ fontWeight: 700, color: activeCompliance?.hasViolation ? '#ef4444' : '#0f172a' }}>
                  {activeCompliance?.hasViolation ? 'Restriction active' : 'Within controlled airspace'}
                </div>
                {zoneRule && (
                  <div style={{ color: '#475569', marginTop: 2 }}>
                    {zoneRule.label} - {zoneRule.message}
                  </div>
                )}
                {activeCompliance && (
                  <div style={{ color: activeCompliance.hasViolation ? '#b91c1c' : '#475569', marginTop: 2 }}>
                    Alt {f.alt_agl.toFixed(1)} / {activeCompliance.maxAltitudeM} m - Speed {f.groundspeed_ms.toFixed(1)} / {activeCompliance.maxSpeedMs} m/s
                  </div>
                )}
              </div>
            </Tooltip>
            <Popup>
              <div style={{ fontSize: 12, minWidth: 150 }}>
                <div style={{ fontWeight: 700, marginBottom: 4 }}>{f.call_sign ?? `Drone #${id}`}</div>
                <div>Lat: {f.lat.toFixed(6)}</div>
                <div>Lon: {f.lon.toFixed(6)}</div>
                <div style={{ color: '#475569', marginTop: 4 }}>Alt AGL: {f.alt_agl.toFixed(1)} m</div>
              </div>
            </Popup>
          </Marker>
        ) : (
          <Marker
            key={`drone-${id}`}
            position={[f.lat, f.lon]}
            icon={droneIcon(f.heading, id === droneId, f.call_sign)}
            eventHandlers={onSelectDrone ? { click: () => onSelectDrone(id) } : undefined}>
            <Popup>
              <div style={{ fontSize: 12, minWidth: 150 }}>
                <div style={{ fontWeight: 700, marginBottom: 4 }}>{f.call_sign ?? `Drone #${id}`}</div>
                <div>Lat: {f.lat.toFixed(6)}</div>
                <div>Lon: {f.lon.toFixed(6)}</div>
                <div style={{ color: '#475569', marginTop: 4 }}>Alt AGL: {f.alt_agl.toFixed(1)} m</div>
              </div>
            </Popup>
          </Marker>
        )
      ))}

      {/* Naval vessel symbols */}
      {positionedVessels.map(v => (
        <Marker
          key={v.id}
          position={[v.latitude!, v.longitude!]}
          icon={vesselIcon(v.heading_deg ?? 0)}>
          <Tooltip permanent direction="top" offset={[0, -20]}>
            <div style={{ fontFamily: 'monospace', fontSize: 11 }}>
              <strong>{v.vessel_id}</strong>
              {v.speed_kts != null && (
                <span> - {v.speed_kts.toFixed(1)} kts {v.heading_deg?.toFixed(0)} deg</span>
              )}
              <div style={{ color: v.deck_status === 'clear' ? '#22c55e' : '#f59e0b' }}>
                deck: {v.deck_status}
              </div>
            </div>
          </Tooltip>
        </Marker>
      ))}
        </MapContainer>

        {(hasPosition && zoneRule || liveRouteCollisions.length > 0) && (
          <div className="da-live-map-alerts" role="toolbar" aria-label="Flight advisories">
            {hasPosition && zoneRule && (
              <button
                type="button"
                className={activeCompliance?.hasViolation ? 'is-danger' : ''}
                onClick={() => setActiveDetail(current => current === 'airspace' ? null : 'airspace')}
                aria-pressed={activeDetail === 'airspace'}>
                <ShieldAlert size={14} />
                <span>{activeCompliance?.hasViolation ? 'Restriction active' : zoneRule.label}</span>
              </button>
            )}
            {liveRouteCollisions.length > 0 && (
              <button
                type="button"
                className="is-warning"
                onClick={() => setActiveDetail(current => current === 'collisions' ? null : 'collisions')}
                aria-pressed={activeDetail === 'collisions'}>
                <AlertTriangle size={14} />
                <span>{liveRouteCollisions.length} path conflict{liveRouteCollisions.length === 1 ? '' : 's'}</span>
              </button>
            )}
          </div>
        )}
      </div>

      {activeDetail && (
        <aside className="da-live-map-detail" aria-label={activeDetail === 'airspace' ? 'Airspace status' : 'Path collision points'}>
          <header>
            <strong>{activeDetail === 'airspace' ? 'Airspace status' : 'Path collision points'}</strong>
            <button type="button" onClick={() => setActiveDetail(null)} title="Close map details">
              <X size={16} />
            </button>
          </header>

          <div className="da-live-map-detail-scroll">
            {activeDetail === 'airspace' && frame && zoneRule && (
              <div className="da-live-map-detail-section">
                <div className={activeCompliance?.hasViolation ? 'da-live-zone-summary is-danger' : 'da-live-zone-summary'}>
                  <ShieldAlert size={17} />
                  <div>
                    <strong>{zoneRule.label}</strong>
                    <span>{zoneRule.message}</span>
                  </div>
                </div>
                <div className="da-live-limit-grid">
                  <div><span>Altitude</span><strong>{frame.alt_agl.toFixed(1)} m</strong><small>Limit {activeCompliance?.maxAltitudeM ?? zoneRule.maxAltitudeM} m</small></div>
                  <div><span>Speed</span><strong>{frame.groundspeed_ms.toFixed(1)} m/s</strong><small>Limit {activeCompliance?.maxSpeedMs ?? zoneRule.maxSpeedMs} m/s</small></div>
                </div>
                {currentRegulatoryZone && (
                  <div className="da-live-regulatory-note">
                    <strong>{currentRegulatoryZone.name}</strong>
                    <span>{currentRegulatoryZone.restriction}</span>
                  </div>
                )}
                {activeCompliance?.altitudeExceeded && <div className="da-live-violation">Altitude limit exceeded</div>}
                {activeCompliance?.speedExceeded && <div className="da-live-violation">Speed limit exceeded</div>}
                {activeCompliance?.geofenceExceeded && (
                  <>
                    <div className="da-live-violation">Geofence block active / automatic RTL protection enabled</div>
                    {onManualControlRequest && (
                      <button type="button" className="da-btn da-btn-danger justify-center" onClick={onManualControlRequest}>
                        Take manual control
                      </button>
                    )}
                  </>
                )}
              </div>
            )}

            {activeDetail === 'collisions' && (
              <div className="da-live-map-detail-section">
                <div className="da-live-collision-summary">
                  <AlertTriangle size={17} />
                  <span>{liveRouteCollisions.length} collision point{liveRouteCollisions.length === 1 ? '' : 's'} detected</span>
                </div>
                {liveRouteCollisions.map((collision, index) => (
                  <div className="da-live-collision-row" key={'live-collision-' + collision.droneAId + '-' + collision.droneBId + '-' + collision.id}>
                    <span>{index + 1}</span>
                    <div>
                      <strong>{formatCollisionCoord(collision)}</strong>
                      <small>{collision.droneAName} / {collision.missionAName}</small>
                      <small>{collision.droneBName} / {collision.missionBName}</small>
                      <small>{collision.distanceM.toFixed(1)} m separation</small>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>
      )}
    </div>
  )
}
