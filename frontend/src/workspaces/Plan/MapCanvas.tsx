import { useMemo, useState } from 'react'
import { MapContainer, Marker, Polygon, Polyline, Popup, TileLayer, useMapEvents } from 'react-leaflet'
import L, { type LeafletEvent } from 'leaflet'
import { Layers, Pencil, Shield, Trash2 } from 'lucide-react'
import { useMissionStore, type GeoPoint } from '@/store/missionStore'

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

function MapClickHandler({ drawing }: { drawing: boolean }) {
  const { draftWaypoints, addWaypoint, geofence, setGeofence } = useMissionStore()
  useMapEvents({
    click(e) {
      if (drawing) {
        setGeofence([...geofence, { lat: e.latlng.lat, lng: e.latlng.lng }])
        return
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

export default function MapCanvas() {
  const {
    draftWaypoints,
    geofence,
    removeWaypoint,
    updateGeofencePoint,
    clearGeofence,
    clearDraft,
  } = useMissionStore()
  const [satellite, setSatellite] = useState(false)
  const [drawing, setDrawing] = useState(false)

  const routePositions = draftWaypoints.map(w => [w.latitude, w.longitude] as [number, number])
  const geofencePositions = geofence.map(p => [p.lat, p.lng] as [number, number])
  const outsideCount = useMemo(
    () => draftWaypoints.filter(w => !isPointInsidePolygon({ lat: w.latitude, lng: w.longitude }, geofence)).length,
    [draftWaypoints, geofence],
  )

  const startDrawing = () => {
    clearGeofence()
    setDrawing(true)
  }

  const finishDrawing = () => {
    if (geofence.length >= 3) setDrawing(false)
  }

  const deleteZone = () => {
    clearGeofence()
    setDrawing(false)
  }

  return (
    <div className="relative h-full w-full">
      <MapContainer
        center={[17.385, 78.4867]}
        zoom={13}
        style={{ height: '100%', width: '100%' }}
        zoomControl>

        {satellite ? (
          <TileLayer
            url="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
            attribution="Google Satellite" />
        ) : (
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="OpenStreetMap" />
        )}

        {geofencePositions.length > 1 && (
          <Polygon
            positions={geofencePositions}
            pathOptions={{
              color: '#0f766e',
              weight: 3,
              fillColor: '#14b8a6',
              fillOpacity: 0.14,
              dashArray: drawing ? '8 6' : undefined,
            }} />
        )}

        {positionsForLine(geofencePositions, drawing).length > 1 && drawing && (
          <Polyline positions={positionsForLine(geofencePositions, drawing)}
            pathOptions={{ color: '#0f766e', weight: 2, dashArray: '4 4', opacity: 0.9 }} />
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
                updateGeofencePoint(idx, { lat: next.lat, lng: next.lng })
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

        <MapClickHandler drawing={drawing} />
      </MapContainer>

      <div className="absolute top-3 right-3 z-[999] flex gap-2">
        <button
          onClick={() => setSatellite(s => !s)}
          className="da-btn da-btn-ghost"
          style={{ background: 'rgba(255,255,255,0.94)', backdropFilter: 'blur(4px)' }}>
          <Layers size={14} />
          {satellite ? 'OSM' : 'Satellite'}
        </button>
      </div>

      <div className="absolute top-3 left-3 z-[999] da-card p-2 flex items-center gap-2">
        <button onClick={startDrawing} className="da-btn da-btn-teal">
          <Pencil size={14} /> Draw Geofence
        </button>
        <button onClick={finishDrawing} disabled={!drawing || geofence.length < 3} className="da-btn da-btn-primary">
          <Shield size={14} /> Finish
        </button>
        <button onClick={deleteZone} disabled={geofence.length === 0} className="da-btn da-btn-ghost">
          <Trash2 size={14} /> Delete
        </button>
        <span className="text-xs mono px-2" style={{ color: outsideCount > 0 ? '#dc2626' : '#0f766e' }}>
          {geofence.length < 3 ? `${geofence.length}/3 vertices` : `${outsideCount} outside`}
        </span>
      </div>

      {draftWaypoints.length === 0 && !drawing && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-[999] px-4 py-2 rounded-full text-xs"
          style={{ background: 'rgba(255,255,255,0.94)', color: '#334155', border: '1px solid var(--da-border)' }}>
          Click the map to place waypoints
        </div>
      )}

      {drawing && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-[999] px-4 py-2 rounded-full text-xs"
          style={{ background: '#ecfeff', color: '#0f766e', border: '1px solid #99f6e4' }}>
          Click at least 3 points, drag vertices to adjust, then finish the geofence
        </div>
      )}

      {(draftWaypoints.length > 0 || geofence.length > 0) && (
        <div className="absolute bottom-6 right-3 z-[999]">
          <button onClick={clearDraft} className="da-btn da-btn-ghost" style={{ background: 'rgba(255,255,255,0.94)' }}>
            <Trash2 size={14} /> Clear mission
          </button>
        </div>
      )}
    </div>
  )
}

function positionsForLine(positions: [number, number][], drawing: boolean) {
  if (!drawing || positions.length < 3) return positions
  return [...positions, positions[0]]
}
