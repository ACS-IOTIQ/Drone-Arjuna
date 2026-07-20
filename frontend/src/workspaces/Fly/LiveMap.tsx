import { useEffect, useMemo, useRef, useState } from 'react'
import { LayersControl, LayerGroup, MapContainer, Marker, Polygon, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet'
import L from 'leaflet'
import { droneControlApi } from '@/api/droneControl'
import { useMissionStore, type GeoPoint } from '@/store/missionStore'
import { notify } from '@/store/notificationStore'
import { useTelemetryStore } from '@/store/telemetryStore'
import { useVesselStore } from '@/store/vesselStore'
import { buildZoneLayers, getZoneRule } from '@/utils/geofenceZones'
import { buildRegulatoryZoneLayers, getRegulatoryRule } from '@/utils/regulatoryZones'

function droneIcon(heading: number, active: boolean, callSign?: string) {
  const size   = active ? 36 : 26
  const fill   = active ? '#3b82f6' : '#94a3b8'
  const stroke = active ? '#1d4ed8' : '#64748b'
  return L.divIcon({
    className: '',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: `<div style="position:relative; width:${size}px; height:${size}px;">
      <div style="
        width:${size}px; height:${size}px;
        display:flex; align-items:center; justify-content:center;
        transform: rotate(${heading}deg);
        opacity:${active ? 1 : 0.85};
      ">
        <svg viewBox="0 0 24 24" width="${size - 8}" height="${size - 8}">
          <polygon points="12,2 7,22 12,18 17,22" fill="${fill}" stroke="${stroke}" stroke-width="1"/>
        </svg>
      </div>
      ${callSign && !active ? `<div style="
        position:absolute; top:100%; left:50%; transform:translateX(-50%);
        white-space:nowrap; font-size:9px; font-weight:600; color:#475569;
        background:rgba(255,255,255,0.85); padding:0 3px; border-radius:2px;
      ">${callSign}</div>` : ''}
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

interface Props {
  droneId: number | null
  onSelectDrone?: (droneId: number) => void
  onManualControlRequest?: () => void
}

export default function LiveMap({ droneId, onSelectDrone, onManualControlRequest }: Props) {
  const frames  = useTelemetryStore(s => s.frames)
  const frame   = droneId ? frames[droneId] : null
  const history = useTelemetryStore(s => droneId ? s.history[droneId] : [])
  const vessels = useVesselStore(s => s.vessels)
  const missionGeofence = useMissionStore(s => s.geofence)
  const [runtimeGeofence, setRuntimeGeofence] = useState<any | null>(null)
  const lastRegulatoryRef = useRef<string | null>(null)
  const lastComplianceRef = useRef<string | null>(null)
  const autoActionRef = useRef<Map<string, number>>(new Map())

  // Breadcrumb trail — every 5th frame, only for the active/followed drone
  const trail = (history ?? [])
    .filter((_, i) => i % 5 === 0)
    .map(f => [f.lat, f.lon] as [number, number])
    .filter(([lat, lon]) => lat !== 0 || lon !== 0)

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
  const zoneRule = useMemo(() => {
    if (!frame) return null
    return getZoneRule(frame.lat, frame.lon, displayGeofence)
  }, [frame, displayGeofence])
  const zoneLayers = useMemo(() => {
    const lat = frame?.lat ?? 0
    const lon = frame?.lon ?? 0
    return buildZoneLayers(lat, lon, displayGeofence)
  }, [frame, displayGeofence])
  const regulatoryZones = useMemo(() => buildRegulatoryZoneLayers(), [])
  const currentRegulatoryZone = useMemo(() => {
    if (!frame) return null
    return getRegulatoryRule(frame.lat, frame.lon, frame.alt_agl ?? 0)
  }, [frame])

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
          `Drone ${droneId} needs manual control for ${currentRegulatoryZone.name}. The app will retry while the violation remains active.`,
          droneId,
        )
      }
    }

    runAutoAction()
  }, [droneId, frame, currentRegulatoryZone])

  // Every connected drone with a known position — rendered simultaneously
  const allDrones = Object.entries(frames)
    .map(([id, f]) => ({ id: Number(id), frame: f }))
    .filter(({ frame: f }) => f && (f.lat !== 0 || f.lon !== 0))

  // Vessels with known positions
  const positionedVessels = vessels.filter(v => v.latitude != null && v.longitude != null)

  return (
    <MapContainer
      center={[17.385, 78.4867]}
      zoom={15}
      style={{ height: '100%', width: '100%' }}
      zoomControl={false}>
      <LayersControl position="bottomright">
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
      {hasPosition && frame && <MapCompass heading={frame.heading} />}

      {trail.length > 1 && (
        <Polyline
          positions={trail}
          pathOptions={{ color: '#3b82f6', weight: 1.5, opacity: 0.5 }} />
      )}

      {allDrones.map(({ id, frame: f }) => (
        id === droneId && frame ? (
          <Marker
            key={`drone-${id}`}
            position={[f.lat, f.lon]}
            icon={droneIcon(f.heading, true, f.call_sign)}
            eventHandlers={onSelectDrone ? { click: () => onSelectDrone(id) } : undefined}>
            <Tooltip permanent direction="top" offset={[0, -16]}>
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
          </Marker>
        ) : (
          <Marker
            key={`drone-${id}`}
            position={[f.lat, f.lon]}
            icon={droneIcon(f.heading, id === droneId, f.call_sign)}
            eventHandlers={onSelectDrone ? { click: () => onSelectDrone(id) } : undefined} />
        )
      ))}

      {hasPosition && frame && zoneRule && (
        <div className="leaflet-top leaflet-left da-zone-advisory" style={{ zIndex: 1000 }}>
          <div className="leaflet-control" style={{ margin: 10, maxWidth: 280 }}>
            <div className="rounded-lg border px-3 py-2 text-xs shadow" style={{
              background: activeCompliance?.hasViolation ? 'rgba(254,242,242,0.97)' : 'rgba(255,255,255,0.96)',
              borderColor: activeCompliance?.hasViolation ? '#fda4af' : '#cbd5e1',
              color: activeCompliance?.hasViolation ? '#b91c1c' : '#334155',
            }}>
              <div className="font-semibold">{zoneRule.label}</div>
              <div className="mt-1">{zoneRule.message}</div>
              <div className="mt-1 text-[10px] uppercase tracking-wide">
                Altitude: {frame.alt_agl.toFixed(1)} / {activeCompliance?.maxAltitudeM ?? zoneRule.maxAltitudeM} m - Speed: {frame.groundspeed_ms.toFixed(1)} / {activeCompliance?.maxSpeedMs ?? zoneRule.maxSpeedMs} m/s
              </div>
              {activeCompliance?.altitudeExceeded && (
                <div className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-red-700">
                  Altitude limit exceeded
                </div>
              )}
              {activeCompliance?.speedExceeded && (
                <div className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-red-700">
                  Speed limit exceeded
                </div>
              )}
              {currentRegulatoryZone && (
                <div className="mt-1 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[10px] text-amber-800">
                  Govt layer: {currentRegulatoryZone.name} - {currentRegulatoryZone.maxAltitudeM} m / {currentRegulatoryZone.maxSpeedMs} m/s
                </div>
              )}
              {activeCompliance?.geofenceExceeded && (
                <div className="mt-2 flex flex-col gap-1">
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-red-700">
                    Geofence block active. Auto-RTL is preventing boundary exit.
                  </div>
                  <button
                    type="button"
                    onClick={onManualControlRequest}
                    className="rounded border border-red-300 bg-white px-2 py-1 text-[11px] font-semibold text-red-700">
                    Take manual control
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

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
  )
}

function MapCompass({ heading }: { heading: number }) {
  const normalized = ((heading % 360) + 360) % 360
  return (
    <div className="leaflet-bottom leaflet-left" style={{ zIndex: 1000 }}>
      <div className="leaflet-control" style={{ margin: 12 }}>
        <div
          title={`Heading ${normalized.toFixed(0)} deg`}
          style={{
            width: 86,
            height: 86,
            borderRadius: '50%',
            background: 'rgba(255,255,255,0.94)',
            border: '1px solid rgba(15,23,42,0.16)',
            boxShadow: '0 8px 22px rgba(15,23,42,0.16)',
            position: 'relative',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backdropFilter: 'blur(8px)',
          }}>
          {[
            ['N', 0, '#dc2626'],
            ['E', 90, '#475569'],
            ['S', 180, '#475569'],
            ['W', 270, '#475569'],
          ].map(([label, deg, color]) => (
            <span
              key={label}
              style={{
                position: 'absolute',
                transform: `rotate(${deg}deg) translateY(-34px) rotate(${-deg}deg)`,
                fontSize: 10,
                fontWeight: 800,
                color: String(color),
              }}>
              {label}
            </span>
          ))}
          <div
            style={{
              position: 'absolute',
              inset: 8,
              borderRadius: '50%',
              border: '1px dashed rgba(71,85,105,0.25)',
              transform: `rotate(${normalized}deg)`,
            }}>
            <div
              style={{
                position: 'absolute',
                left: '50%',
                top: 6,
                width: 0,
                height: 0,
                transform: 'translateX(-50%)',
                borderLeft: '6px solid transparent',
                borderRight: '6px solid transparent',
                borderBottom: '22px solid #2563eb',
              }}
            />
          </div>
          <div style={{ textAlign: 'center', lineHeight: 1 }}>
            <div className="mono" style={{ fontSize: 16, fontWeight: 800, color: '#0f172a' }}>{normalized.toFixed(0)}</div>
            <div style={{ fontSize: 8, fontWeight: 700, color: '#64748b', marginTop: 2 }}>HDG</div>
          </div>
        </div>
      </div>
    </div>
  )
}
