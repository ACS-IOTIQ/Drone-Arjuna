import { useEffect, useMemo, useState } from 'react'
import { LayersControl, LayerGroup, MapContainer, Marker, Polygon, Polyline, Popup, TileLayer, useMapEvents, ZoomControl } from 'react-leaflet'
import L, { type LeafletEvent } from 'leaflet'
import { CheckCircle2, Pencil, PlusCircle, Route, Shield, Trash2 } from 'lucide-react'
import { useMissionStore, type GeoPoint } from '@/store/missionStore'
import { notify } from '@/store/notificationStore'
import { buildZoneLayers } from '@/utils/geofenceZones'
import { buildRegulatoryZoneLayers, getRegulatoryRule } from '@/utils/regulatoryZones'

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

function validateGovernmentPlacement(lat: number, lng: number, target: 'waypoint' | 'geofence vertex') {
  const rule = getRegulatoryRule(lat, lng, 0)
  if (!rule) return true

  if (rule.kind === 'red') {
    notify.danger(
      'Point blocked in red zone',
      `Cannot place ${target} inside ${rule.name}. ${rule.restriction}`,
    )
    return false
  }

  if (rule.kind === 'orange') {
    notify.warning(
      'Point placed in orange zone',
      `${target} is inside ${rule.name}. ${rule.restriction}`,
    )
  }

  return true
}

function MapClickHandler({ drawing, routeDrawing }: { drawing: boolean; routeDrawing: boolean }) {
  const { draftWaypoints, addWaypoint, geofence, setGeofence } = useMissionStore()
  useMapEvents({
    click(e) {
      if (drawing) {
        if (!validateGovernmentPlacement(e.latlng.lat, e.latlng.lng, 'geofence vertex')) return
        setGeofence([...geofence, { lat: e.latlng.lat, lng: e.latlng.lng }])
        return
      }

      if (!routeDrawing) return
      if (!validateGovernmentPlacement(e.latlng.lat, e.latlng.lng, 'waypoint')) return

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
    setGeofence,
    activeMissionId,
  } = useMissionStore()
  const [drawing, setDrawing] = useState(false)
  const [routeDrawing, setRouteDrawing] = useState(true)
  const [manualLat, setManualLat] = useState('')
  const [manualLng, setManualLng] = useState('')

  const routePositions = draftWaypoints.map(w => [w.latitude, w.longitude] as [number, number])
  const geofencePositions = geofence.map(p => [p.lat, p.lng] as [number, number])
  const zoneLayers = useMemo(() => {
    if (geofence.length < 3) return []
    const centerLat = geofence.reduce((sum, p) => sum + p.lat, 0) / geofence.length
    const centerLng = geofence.reduce((sum, p) => sum + p.lng, 0) / geofence.length
    return buildZoneLayers(centerLat, centerLng, geofence)
  }, [geofence])
  const regulatoryZones = useMemo(() => buildRegulatoryZoneLayers(), [])
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
    if (geofence.length >= 3) setDrawing(false)
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
    setGeofence([...geofence, { lat, lng }])
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
              {regulatoryZones.map(layer => (
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
                if (!validateGovernmentPlacement(next.lat, next.lng, 'geofence vertex')) {
                  marker.setLatLng([point.lat, point.lng])
                  return
                }
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

        <MapClickHandler drawing={drawing} routeDrawing={routeDrawing} />
      </MapContainer>

      <div className="absolute top-3 left-3 z-[999] da-card p-2 flex flex-col gap-2">
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
    </div>
  )
}

function positionsForLine(positions: [number, number][], drawing: boolean) {
  if (!drawing || positions.length < 3) return positions
  return [...positions, positions[0]]
}
