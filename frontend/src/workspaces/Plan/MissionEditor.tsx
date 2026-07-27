import { useState } from 'react'
import {
  Anchor,
  FileText,
  FolderOpen,
  MapPin,
  Play,
  Route,
  Save,
  Trash2,
} from 'lucide-react'
import { useMissionStore } from '@/store/missionStore'
import { useFleetStore } from '@/store/fleetStore'
import { useVesselStore } from '@/store/vesselStore'
import { droneFlightApi } from '@/api/droneFlight'
import { notify } from '@/store/notificationStore'

type EditorSection = 'details' | 'waypoints' | 'geofence' | 'missions'

export default function MissionEditor() {
  const {
    draftWaypoints,
    geofence,
    missions,
    saveMission,
    removeWaypoint,
    loadMission,
    setGeofence,
  } = useMissionStore()
  const { instances } = useFleetStore()
  const { vessels } = useVesselStore()

  const [section, setSection] = useState<EditorSection>('details')
  const [name, setName] = useState('')
  const [type, setType] = useState('ISR')
  const [droneId, setDroneId] = useState<number | undefined>()
  const [homeType, setHomeType] = useState<'fixed' | 'dynamic_vessel'>('fixed')
  const [homeVesselId, setHomeVesselId] = useState<number | undefined>()
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(false)
  const [summary, setSummary] = useState<any>(null)
  const [err, setErr] = useState('')

  const estimate = async () => {
    if (draftWaypoints.length < 2) return
    try {
      const { data: mission } = await droneFlightApi.createMission({
        name: '_preview',
        waypoints: draftWaypoints,
      })
      const { data } = await droneFlightApi.getMissionSummary(mission.id)
      setSummary(data)
      await droneFlightApi.deleteMission(mission.id)
      setSection('details')
    } catch {
      // Estimation is optional and does not block editing.
    }
  }

  const load = async (id: number) => {
    setLoading(true)
    setErr('')
    setSummary(null)
    try {
      const meta = await loadMission(id)
      setName(meta.name)
      setType(meta.mission_type)
      setDroneId(meta.drone_instance_id ?? undefined)
      setHomeType((meta.home_point_type as 'fixed' | 'dynamic_vessel') ?? 'fixed')
      setHomeVesselId(meta.home_vessel_id ?? undefined)
      setSection('details')
    } catch {
      setErr('Failed to load mission')
    } finally {
      setLoading(false)
    }
  }

  const extractApiError = (error: any): string => {
    const detail = error?.response?.data?.detail
    if (!detail) return 'Save failed'
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail?.errors)) return detail.errors.join('\n')
    if (detail?.message) return detail.message
    return 'Save failed'
  }

  const save = async () => {
    if (!name.trim() || draftWaypoints.length === 0) return
    if (homeType === 'dynamic_vessel' && !homeVesselId) {
      setErr('Select a home vessel for ship-based operations')
      return
    }
    setSaving(true)
    setErr('')
    try {
      await saveMission(name, type, droneId, homeType, homeVesselId)
      setName('')
    } catch (error: any) {
      const message = extractApiError(error)
      setErr(message)
      notify.danger('Mission save blocked', message)
    } finally {
      setSaving(false)
    }
  }

  const tabs: Array<{ id: EditorSection; label: string; icon: React.ReactNode; count?: number }> = [
    { id: 'details', label: 'Details', icon: <FileText size={14} /> },
    { id: 'waypoints', label: 'Route', icon: <Route size={14} />, count: draftWaypoints.length },
    { id: 'geofence', label: 'Fence', icon: <MapPin size={14} />, count: geofence.length },
    { id: 'missions', label: 'Saved', icon: <FolderOpen size={14} />, count: missions.length },
  ]

  return (
    <div className="da-mission-editor">
      <div className="da-mission-editor-header">
        <div className="min-w-0">
          <h2>Mission Editor</h2>
          <p>{loading ? 'Loading mission...' : `${draftWaypoints.length} waypoints / ${geofence.length} fence vertices`}</p>
        </div>
      </div>

      <nav className="da-mission-tabs" aria-label="Mission editor sections">
        {tabs.map(tab => (
          <button
            key={tab.id}
            type="button"
            className={section === tab.id ? 'is-active' : ''}
            onClick={() => setSection(tab.id)}
            aria-current={section === tab.id ? 'page' : undefined}>
            {tab.icon}
            <span>{tab.label}</span>
            {tab.count !== undefined && <b>{tab.count}</b>}
          </button>
        ))}
      </nav>

      <div className="da-mission-editor-scroll">
        {err && <div className="da-mission-error" role="alert">{err}</div>}

        {section === 'details' && (
          <div className="da-mission-section">
            <label className="da-mission-field">
              <span>Mission name</span>
              <input
                className="da-input"
                placeholder="ALPHA-7"
                value={name}
                onChange={event => setName(event.target.value)}
              />
            </label>

            <label className="da-mission-field">
              <span>Type</span>
              <select className="da-input" value={type} onChange={event => setType(event.target.value)}>
                {['ISR', 'Strike', 'Patrol', 'Logistics', 'SAR', 'Training'].map(item => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>

            <label className="da-mission-field">
              <span>Assigned drone</span>
              <select
                className="da-input"
                value={droneId ?? ''}
                onChange={event => setDroneId(event.target.value ? Number(event.target.value) : undefined)}>
                <option value="">Unassigned</option>
                {instances.map(drone => (
                  <option key={drone.id} value={drone.id}>{drone.call_sign}</option>
                ))}
              </select>
            </label>

            <label className="da-mission-field">
              <span>Home point</span>
              <select
                className="da-input"
                value={homeType}
                onChange={event => {
                  const next = event.target.value as 'fixed' | 'dynamic_vessel'
                  setHomeType(next)
                  if (next === 'fixed') setHomeVesselId(undefined)
                }}>
                <option value="fixed">Fixed ground base</option>
                <option value="dynamic_vessel">Dynamic return to ship</option>
              </select>
            </label>

            {homeType === 'dynamic_vessel' && (
              <div className="da-mission-vessel">
                <div className="da-mission-vessel-title">
                  <Anchor size={14} /> Home vessel
                </div>
                <select
                  className="da-input"
                  value={homeVesselId ?? ''}
                  onChange={event => setHomeVesselId(event.target.value ? Number(event.target.value) : undefined)}>
                  <option value="">Select vessel</option>
                  {vessels.map(vessel => (
                    <option key={vessel.id} value={vessel.id}>
                      {vessel.vessel_id} - {vessel.name} {vessel.latitude != null ? '(position known)' : '(no position)'}
                    </option>
                  ))}
                </select>
                {vessels.length === 0 && <p>No vessels registered.</p>}
                {homeVesselId && vessels.find(vessel => vessel.id === homeVesselId)?.latitude == null && (
                  <p>The selected vessel has no current position.</p>
                )}
              </div>
            )}

            {summary && (
              <div className="da-mission-summary">
                <span>Distance</span><strong>{summary.total_distance_km} km</strong>
                <span>Estimated time</span><strong>{summary.estimated_flight_time_min} min</strong>
                <span>Battery estimate</span>
                <strong className={summary.estimated_battery_pct > 80 ? 'is-danger' : ''}>
                  {summary.estimated_battery_pct}%
                </strong>
              </div>
            )}
          </div>
        )}

        {section === 'waypoints' && (
          <div className="da-mission-section da-mission-list-section">
            {draftWaypoints.length === 0 ? (
              <EmptyState icon={<Route size={20} />} label="No waypoints plotted" />
            ) : (
              draftWaypoints.map((waypoint, index) => (
                <WaypointRow
                  key={waypoint.sequence}
                  wp={waypoint}
                  idx={index}
                  onRemove={() => removeWaypoint(waypoint.sequence)}
                />
              ))
            )}
          </div>
        )}

        {section === 'geofence' && (
          <div className="da-mission-section da-mission-list-section">
            {geofence.length === 0 ? (
              <EmptyState icon={<MapPin size={20} />} label="No geofence vertices" />
            ) : (
              <>
                {geofence.map((point, index) => (
                  <div className="da-coordinate-row" key={`${index}-${point.lat}-${point.lng}`}>
                    <span className="da-coordinate-index">{index + 1}</span>
                    <div>
                      <span>Longitude {point.lng.toFixed(6)}</span>
                      <span>Latitude {point.lat.toFixed(6)}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setGeofence(geofence.filter((_, itemIndex) => itemIndex !== index))}
                      title={`Remove geofence vertex ${index + 1}`}>
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
                <button type="button" className="da-btn da-btn-ghost justify-center" onClick={() => setGeofence([])}>
                  <Trash2 size={13} /> Clear geofence
                </button>
              </>
            )}
          </div>
        )}

        {section === 'missions' && (
          <div className="da-mission-section da-mission-list-section">
            {missions.length === 0 ? (
              <EmptyState icon={<FolderOpen size={20} />} label="No saved missions" />
            ) : (
              missions.map(mission => (
                <div className="da-saved-mission-row" key={mission.id}>
                  <div className="min-w-0 flex-1">
                    <strong>{mission.name}</strong>
                    <span>{mission.mission_type} / {mission.waypoints?.length ?? 0} waypoints</span>
                  </div>
                  <span className={`da-plan-status-chip ${mission.status}`}>{mission.status}</span>
                  <button
                    type="button"
                    className="da-plan-icon-btn"
                    onClick={() => load(mission.id)}
                    disabled={loading}
                    title={`Load ${mission.name}`}>
                    <FolderOpen size={14} />
                  </button>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      <footer className="da-mission-editor-footer">
        <button
          type="button"
          className="da-btn da-btn-ghost justify-center"
          onClick={estimate}
          disabled={draftWaypoints.length < 2}>
          <Play size={13} /> Estimate
        </button>
        <button
          type="button"
          className="da-btn da-btn-primary justify-center"
          onClick={save}
          disabled={saving || !name.trim() || draftWaypoints.length === 0}>
          <Save size={14} /> {saving ? 'Saving...' : 'Save Mission'}
        </button>
      </footer>
    </div>
  )
}

function EmptyState({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div className="da-mission-empty">
      {icon}
      <span>{label}</span>
    </div>
  )
}

function WaypointRow({ wp, idx, onRemove }: { wp: any; idx: number; onRemove: () => void }) {
  return (
    <div className="da-waypoint-row">
      <span className={wp.is_home ? 'da-waypoint-index is-home' : 'da-waypoint-index'}>
        {wp.is_home ? 'H' : idx + 1}
      </span>
      <div className="min-w-0 flex-1">
        <strong>{wp.is_home ? 'Home / Takeoff' : `Waypoint ${idx + 1}`}</strong>
        <span className="mono">{wp.longitude.toFixed(6)}, {wp.latitude.toFixed(6)}</span>
        <span>{wp.altitude_m} m {wp.altitude_ref}</span>
      </div>
      <button type="button" onClick={onRemove} title={`Remove waypoint ${idx + 1}`}>
        <Trash2 size={13} />
      </button>
    </div>
  )
}
