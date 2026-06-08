import { useState } from 'react'
import { Save, Trash2, Play, Anchor, FolderOpen } from 'lucide-react'
import { useMissionStore } from '@/store/missionStore'
import { useFleetStore } from '@/store/fleetStore'
import { useVesselStore } from '@/store/vesselStore'
import { droneFlightApi } from '@/api/droneFlight'

export default function MissionEditor() {
  const { draftWaypoints, missions, saveMission, removeWaypoint, loadMission } = useMissionStore()
  const { instances } = useFleetStore()
  const { vessels } = useVesselStore()

  const [name, setName]               = useState('')
  const [type, setType]               = useState('ISR')
  const [droneId, setDroneId]         = useState<number | undefined>()
  const [homeType, setHomeType]       = useState<'fixed' | 'dynamic_vessel'>('fixed')
  const [homeVesselId, setHomeVesselId] = useState<number | undefined>()
  const [saving, setSaving]           = useState(false)
  const [loading, setLoading]         = useState(false)
  const [summary, setSummary]         = useState<any>(null)
  const [err, setErr]                 = useState('')

  // Estimate summary from draft
  const estimate = async () => {
    if (draftWaypoints.length < 2) return
    // Save temp mission to get server-side calculation
    try {
      const { data: m } = await droneFlightApi.createMission({
        name: '_preview', waypoints: draftWaypoints,
      })
      const { data: s } = await droneFlightApi.getMissionSummary(m.id)
      setSummary(s)
      await droneFlightApi.deleteMission(m.id)
    } catch { /* ignore */ }
  }

  const load = async (id: number) => {
    setLoading(true); setErr(''); setSummary(null)
    try {
      const meta = await loadMission(id)
      setName(meta.name)
      setType(meta.mission_type)
      setDroneId(meta.drone_instance_id ?? undefined)
      setHomeType((meta.home_point_type as 'fixed' | 'dynamic_vessel') ?? 'fixed')
      setHomeVesselId(meta.home_vessel_id ?? undefined)
    } catch {
      setErr('Failed to load mission')
    } finally {
      setLoading(false)
    }
  }

  const save = async () => {
    if (!name.trim() || draftWaypoints.length === 0) return
    if (homeType === 'dynamic_vessel' && !homeVesselId) {
      setErr('Select a home vessel for ship-based operations'); return
    }
    setSaving(true); setErr('')
    try {
      await saveMission(name, type, droneId, homeType, homeVesselId)
      setName('')
    } catch (e: any) {
      setErr(e.response?.data?.detail ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Panel header */}
      <div className="px-4 py-3" style={{ borderBottom: '1px solid var(--da-border)' }}>
        <h3 className="text-sm font-semibold">Mission Editor</h3>
        <p className="text-xs mt-0.5" style={{ color: '#6b7280' }}>
          {loading ? 'Loading mission…' : `${draftWaypoints.length} waypoints placed`}
        </p>
      </div>

      {/* Mission meta */}
      <div className="p-4 flex flex-col gap-3" style={{ borderBottom: '1px solid var(--da-border)' }}>
        <label className="flex flex-col gap-1">
          <span className="text-xs" style={{ color: '#94a3b8' }}>MISSION NAME</span>
          <input className="da-input" placeholder="ALPHA-7" value={name}
            onChange={e => setName(e.target.value)} />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs" style={{ color: '#94a3b8' }}>TYPE</span>
          <select className="da-input" value={type} onChange={e => setType(e.target.value)}>
            {['ISR', 'Strike', 'Patrol', 'Logistics', 'SAR', 'Training'].map(t => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs" style={{ color: '#94a3b8' }}>ASSIGN DRONE</span>
          <select className="da-input" value={droneId ?? ''}
            onChange={e => setDroneId(e.target.value ? Number(e.target.value) : undefined)}>
            <option value="">— Unassigned —</option>
            {instances.map(d => (
              <option key={d.id} value={d.id}>{d.call_sign}</option>
            ))}
          </select>
        </label>

        {/* Home point type */}
        <label className="flex flex-col gap-1">
          <span className="text-xs" style={{ color: '#94a3b8' }}>HOME POINT</span>
          <select className="da-input" value={homeType}
            onChange={e => {
              setHomeType(e.target.value as any)
              if (e.target.value === 'fixed') setHomeVesselId(undefined)
            }}>
            <option value="fixed">Fixed (ground base)</option>
            <option value="dynamic_vessel">Dynamic — Return to Ship (HF)</option>
          </select>
        </label>

        {homeType === 'dynamic_vessel' && (
          <div className="flex flex-col gap-2 p-3 rounded"
            style={{ background: 'rgba(6,182,212,0.07)', border: '1px solid rgba(6,182,212,0.2)' }}>
            <div className="flex items-center gap-1.5 mb-1">
              <Anchor size={12} style={{ color: '#06b6d4' }} />
              <span className="text-xs font-medium" style={{ color: '#06b6d4' }}>Home Vessel</span>
            </div>
            <select className="da-input" value={homeVesselId ?? ''}
              onChange={e => setHomeVesselId(e.target.value ? Number(e.target.value) : undefined)}>
              <option value="">— Select vessel —</option>
              {vessels.map(v => (
                <option key={v.id} value={v.id}>
                  {v.vessel_id} — {v.name}
                  {v.latitude != null ? ` (pos known)` : ' (no position)'}
                </option>
              ))}
            </select>
            {vessels.length === 0 && (
              <p className="text-[11px]" style={{ color: '#f59e0b' }}>
                No vessels registered. Add one in Settings → Naval Vessels.
              </p>
            )}
            {homeVesselId && vessels.find(v => v.id === homeVesselId)?.latitude == null && (
              <p className="text-[11px]" style={{ color: '#f59e0b' }}>
                Vessel has no current position — range estimation will be unavailable.
              </p>
            )}
            <p className="text-[11px]" style={{ color: '#4b5563' }}>
              Home waypoint will be set to the vessel's current GPS position at upload time.
              The return coordinate updates continuously via the HF position feed.
            </p>
          </div>
        )}
      </div>

      {/* Summary estimate */}
      {summary && (
        <div className="mx-4 mt-3 p-3 rounded text-xs grid grid-cols-2 gap-2"
          style={{ background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.2)' }}>
          <span style={{ color: '#6b7280' }}>Distance</span>
          <span className="mono text-right">{summary.total_distance_km} km</span>
          <span style={{ color: '#6b7280' }}>Est. time</span>
          <span className="mono text-right">{summary.estimated_flight_time_min} min</span>
          <span style={{ color: '#6b7280' }}>Battery est.</span>
          <span className="mono text-right" style={{ color: summary.estimated_battery_pct > 80 ? '#ef4444' : '#94a3b8' }}>
            {summary.estimated_battery_pct}%
          </span>
        </div>
      )}

      {/* Waypoint list */}
      <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-1">
        {draftWaypoints.length === 0 ? (
          <p className="text-xs text-center py-8" style={{ color: '#374151' }}>
            Click the map to add waypoints
          </p>
        ) : (
          draftWaypoints.map((wp, i) => (
            <WaypointRow key={wp.sequence} wp={wp} idx={i}
              onRemove={() => removeWaypoint(wp.sequence)} />
          ))
        )}
      </div>

      {/* Action buttons */}
      <div className="p-4 flex flex-col gap-2" style={{ borderTop: '1px solid var(--da-border)' }}>
        {err && <p className="text-xs" style={{ color: '#ef4444' }}>{err}</p>}
        <button className="da-btn da-btn-ghost justify-center text-xs"
          onClick={estimate} disabled={draftWaypoints.length < 2}>
          <Play size={12} /> Estimate flight
        </button>
        <button className="da-btn da-btn-primary justify-center"
          onClick={save} disabled={saving || !name || draftWaypoints.length === 0}>
          <Save size={14} />
          {saving ? 'Saving…' : 'Save Mission'}
        </button>
      </div>

      {/* Saved missions list */}
      {missions.length > 0 && (
        <div className="px-4 pb-4">
          <p className="text-xs font-medium mb-2" style={{ color: '#6b7280' }}>SAVED MISSIONS</p>
          {missions.slice(0, 5).map(m => (
            <div key={m.id} className="flex items-center gap-2 py-1.5 border-b text-xs"
              style={{ borderColor: 'var(--da-border)' }}>
              <span className="flex-1 truncate" style={{ color: '#94a3b8' }}>{m.name}</span>
              <span className="da-badge shrink-0" style={{
                background: m.status === 'planning' ? 'rgba(107,114,128,0.2)' : 'rgba(34,197,94,0.15)',
                color: m.status === 'planning' ? '#6b7280' : '#22c55e',
              }}>{m.status}</span>
              <button
                onClick={() => load(m.id)}
                disabled={loading}
                title="Load into editor"
                className="shrink-0 flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] transition-colors"
                style={{ background: 'rgba(59,130,246,0.12)', color: '#3b82f6' }}>
                <FolderOpen size={10} />
                Load
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function WaypointRow({ wp, idx, onRemove }: { wp: any; idx: number; onRemove: () => void }) {
  return (
    <div className="flex items-center gap-2 px-2 py-1.5 rounded text-xs group"
      style={{ background: 'rgba(255,255,255,0.02)' }}>
      <span className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0"
        style={{ background: wp.is_home ? '#22c55e' : '#3b82f6', color: 'white' }}>
        {wp.is_home ? 'H' : wp.sequence}
      </span>
      <div className="flex-1 min-w-0">
        <span className="mono" style={{ color: '#94a3b8' }}>
          {wp.latitude.toFixed(4)}, {wp.longitude.toFixed(4)}
        </span>
        <span className="ml-2" style={{ color: '#4b5563' }}>{wp.altitude_m}m {wp.altitude_ref}</span>
      </div>
      <button onClick={onRemove}
        className="opacity-0 group-hover:opacity-100 transition-opacity"
        style={{ color: '#ef4444' }}>
        <Trash2 size={12} />
      </button>
    </div>
  )
}