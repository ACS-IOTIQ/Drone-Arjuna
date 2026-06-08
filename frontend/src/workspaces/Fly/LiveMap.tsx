import { useEffect, useRef } from 'react'
import { MapContainer, TileLayer, Marker, Polyline, Tooltip, useMap } from 'react-leaflet'
import L from 'leaflet'
import { useTelemetryStore } from '@/store/telemetryStore'
import { useVesselStore } from '@/store/vesselStore'

function droneIcon(heading: number) {
  return L.divIcon({
    className: '',
    iconSize: [36, 36],
    iconAnchor: [18, 18],
    html: `<div style="
      width:36px; height:36px;
      display:flex; align-items:center; justify-content:center;
      transform: rotate(${heading}deg);
    ">
      <svg viewBox="0 0 24 24" width="28" height="28">
        <polygon points="12,2 7,22 12,18 17,22" fill="#3b82f6" stroke="#1d4ed8" stroke-width="1"/>
      </svg>
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
        <!-- Ship hull outline pointing north -->
        <path d="M12 2 L17 8 L17 17 L12 20 L7 17 L7 8 Z"
              fill="#06b6d4" fill-opacity="0.85" stroke="#0891b2" stroke-width="1.2"/>
        <!-- Bow indicator -->
        <line x1="12" y1="2" x2="12" y2="5" stroke="#ffffff" stroke-width="1.5"/>
      </svg>
    </div>`,
  })
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
  }, [lat, lon])

  return null
}

interface Props { droneId: number | null }

export default function LiveMap({ droneId }: Props) {
  const frame   = useTelemetryStore(s => droneId ? s.frames[droneId] : null)
  const history = useTelemetryStore(s => droneId ? s.history[droneId] : [])
  const vessels = useVesselStore(s => s.vessels)

  // Breadcrumb trail — every 5th frame
  const trail = (history ?? [])
    .filter((_, i) => i % 5 === 0)
    .map(f => [f.lat, f.lon] as [number, number])
    .filter(([lat, lon]) => lat !== 0 || lon !== 0)

  const hasPosition = frame && (frame.lat !== 0 || frame.lon !== 0)

  // Vessels with known positions
  const positionedVessels = vessels.filter(v => v.latitude != null && v.longitude != null)

  return (
    <MapContainer
      center={[17.385, 78.4867]}
      zoom={15}
      style={{ height: '100%', width: '100%' }}
      zoomControl={false}>

      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution="© OpenStreetMap" />

      {hasPosition && (
        <>
          <MapFollower lat={frame.lat} lon={frame.lon} />

          {trail.length > 1 && (
            <Polyline
              positions={trail}
              pathOptions={{ color: '#3b82f6', weight: 1.5, opacity: 0.5 }} />
          )}

          <Marker
            key={`drone-${droneId}`}
            position={[frame.lat, frame.lon]}
            icon={droneIcon(frame.heading)} />
        </>
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
                <span> · {v.speed_kts.toFixed(1)} kts {v.heading_deg?.toFixed(0)}°</span>
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