import { useCallback } from 'react'
import { MapContainer, TileLayer, Marker, Polyline, Popup, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import { useMissionStore } from '@/store/missionStore'
import { Layers, Trash2 } from 'lucide-react'
import { useState } from 'react'

// Numbered waypoint icon factory
function wpIcon(seq: number, isHome: boolean) {
  return L.divIcon({
    className: '',
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    html: `<div style="
      width:28px; height:28px; border-radius:50%;
      background:${isHome ? '#22c55e' : '#3b82f6'};
      border:2px solid ${isHome ? '#16a34a' : '#1d4ed8'};
      display:flex; align-items:center; justify-content:center;
      color:white; font-size:11px; font-weight:700;
      box-shadow:0 2px 8px rgba(0,0,0,0.5);
    ">${isHome ? 'H' : seq}</div>`,
  })
}

function ClickHandler() {
  const { draftWaypoints, addWaypoint } = useMissionStore()
  useMapEvents({
    click(e) {
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

export default function MapCanvas() {
  const { draftWaypoints, removeWaypoint } = useMissionStore()
  const [satellite, setSatellite] = useState(false)

  const positions = draftWaypoints.map(w => [w.latitude, w.longitude] as [number, number])

  return (
    <div className="relative h-full w-full">
      <MapContainer
        center={[17.385, 78.4867]}   // Hyderabad default
        zoom={13}
        style={{ height: '100%', width: '100%' }}
        zoomControl={false}>

        {/* Base layer toggle */}
        {satellite ? (
          <TileLayer
            url="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
            attribution="Google Satellite" />
        ) : (
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="© OpenStreetMap" />
        )}

        {/* Route polyline */}
        {positions.length > 1 && (
          <Polyline positions={positions}
            pathOptions={{ color: '#3b82f6', weight: 2, dashArray: '6 4', opacity: 0.8 }} />
        )}

        {/* Waypoint markers */}
        {draftWaypoints.map(wp => (
          <Marker
            key={wp.sequence}
            position={[wp.latitude, wp.longitude]}
            icon={wpIcon(wp.sequence, !!wp.is_home)}>
            <Popup>
              <div style={{ background: '#1a2235', color: '#e2e8f0', padding: 8, borderRadius: 6, minWidth: 160 }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>
                  {wp.is_home ? 'Home / Takeoff' : `Waypoint ${wp.sequence}`}
                </div>
                <div style={{ fontSize: 11, color: '#94a3b8' }}>
                  {wp.latitude.toFixed(5)}, {wp.longitude.toFixed(5)}
                </div>
                <div style={{ fontSize: 11, color: '#94a3b8' }}>
                  Alt: {wp.altitude_m} m {wp.altitude_ref}
                </div>
                <button
                  onClick={() => removeWaypoint(wp.sequence)}
                  style={{
                    marginTop: 8, width: '100%', padding: '4px 0',
                    background: 'rgba(239,68,68,0.15)', color: '#ef4444',
                    border: '1px solid rgba(239,68,68,0.3)', borderRadius: 4,
                    fontSize: 11, cursor: 'pointer',
                  }}>
                  Remove waypoint
                </button>
              </div>
            </Popup>
          </Marker>
        ))}

        <ClickHandler />
      </MapContainer>

      {/* Layer toggle overlay */}
      <div className="absolute top-3 right-3 z-[999]">
        <button
          onClick={() => setSatellite(s => !s)}
          className="da-btn da-btn-ghost"
          style={{ background: 'rgba(17,24,39,0.9)', backdropFilter: 'blur(4px)' }}>
          <Layers size={14} />
          {satellite ? 'OSM' : 'Satellite'}
        </button>
      </div>

      {/* Click instruction */}
      {draftWaypoints.length === 0 && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-[999] px-4 py-2 rounded-full text-xs"
          style={{ background: 'rgba(17,24,39,0.85)', color: '#94a3b8', border: '1px solid var(--da-border)' }}>
          Click the map to place waypoints
        </div>
      )}

      {/* Clear all */}
      {draftWaypoints.length > 0 && (
        <div className="absolute bottom-6 right-3 z-[999]">
          <button onClick={() => useMissionStore.getState().clearDraft()}
            className="da-btn da-btn-ghost"
            style={{ background: 'rgba(17,24,39,0.9)' }}>
            <Trash2 size={14} /> Clear all
          </button>
        </div>
      )}
    </div>
  )
}