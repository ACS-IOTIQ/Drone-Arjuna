import { useEffect, useMemo, useState } from 'react'
import { Activity, CheckCircle2, PanelLeft, Send, XCircle } from 'lucide-react'
import { useMissionStore } from '@/store/missionStore'
import { useFleetStore } from '@/store/fleetStore'
import { useVesselStore } from '@/store/vesselStore'
import MapCanvas from './MapCanvas'
import MissionEditor from './MissionEditor'
import LiveOpsPanel from './LiveOpsPanel'
import FleetAssignModal from './FleetAssignModal'

export default function PlanWorkspace() {
  const { missions, activeMissionId, fetchMissions, updateMissionStatus } = useMissionStore()
  const fetchInstances = useFleetStore(s => s.fetchInstances)
  const fetchConnections = useFleetStore(s => s.fetchConnections)
  const fetchVessels = useVesselStore(s => s.fetchVessels)
  const [busyAction, setBusyAction] = useState('')
  const [actionErr, setActionErr] = useState('')
  const [showFleetAssign, setShowFleetAssign] = useState(false)
  const [editorOpen, setEditorOpen] = useState(true)
  const [liveOpsOpen, setLiveOpsOpen] = useState(false)

  useEffect(() => {
    fetchMissions()
    fetchInstances()
    fetchConnections()
    fetchVessels()
  }, [])

  const activeMission = useMemo(
    () => missions.find(m => m.id === activeMissionId),
    [missions, activeMissionId],
  )

  const updateStatus = async (label: string, status: 'planning' | 'approved' | 'aborted') => {
    if (!activeMissionId) return
    setBusyAction(label); setActionErr('')
    try {
      await updateMissionStatus(activeMissionId, status)
    } catch (e: any) {
      const detail = e.response?.data?.detail
      const msg = typeof detail === 'string'
        ? detail
        : detail?.message ?? `${label} failed`
      setActionErr(msg)
    } finally {
      setBusyAction('')
    }
  }

  const toggleEditor = () => {
    setEditorOpen(open => {
      const next = !open
      if (next) setLiveOpsOpen(false)
      return next
    })
  }

  const toggleLiveOps = () => {
    setLiveOpsOpen(open => {
      const next = !open
      if (next) setEditorOpen(false)
      return next
    })
  }

  return (
    <div className={`da-plan-layout flex h-full min-h-0 flex-col overflow-hidden ${editorOpen ? 'editor-open' : ''} ${liveOpsOpen ? 'liveops-open' : ''}`}>
      <header className="da-plan-header">
        <div className="da-plan-header-primary">
          <button
            type="button"
            className={editorOpen ? 'da-plan-icon-btn is-active' : 'da-plan-icon-btn'}
            onClick={toggleEditor}
            title={editorOpen ? 'Close mission editor' : 'Open mission editor'}
            aria-pressed={editorOpen}>
            <PanelLeft size={17} />
          </button>
          <div className="da-plan-mission-identity">
            <span>Active mission</span>
            <strong>{activeMission?.name ?? 'Unsaved mission'}</strong>
          </div>
          <span className={`da-plan-status-chip ${activeMission?.status ?? 'draft'}`}>
            {activeMission?.status ?? 'draft'}
          </span>
        </div>

        <div className="da-plan-header-actions">
          <button
            type="button"
            className={liveOpsOpen ? 'da-btn da-btn-teal' : 'da-btn da-btn-ghost'}
            onClick={toggleLiveOps}
            title={liveOpsOpen ? 'Close Live Ops' : 'Open Live Ops'}
            aria-pressed={liveOpsOpen}>
            <Activity size={14} /> <span className="da-plan-btn-label">Live Ops</span>
          </button>
          <button
            className="da-btn da-btn-ghost"
            disabled={!activeMissionId || !!busyAction}
            title="Submit mission"
            onClick={() => updateStatus('Submit', 'planning')}>
            <Send size={14} /> <span className="da-plan-btn-label">{busyAction === 'Submit' ? 'Submitting...' : 'Submit'}</span>
          </button>
          <button
            className="da-btn da-btn-success"
            disabled={!activeMissionId || !!busyAction}
            title="Approve mission"
            onClick={() => updateStatus('Approve', 'approved')}>
            <CheckCircle2 size={14} /> <span className="da-plan-btn-label">{busyAction === 'Approve' ? 'Approving...' : 'Approve'}</span>
          </button>
          <button
            className="da-btn da-btn-danger"
            disabled={!activeMissionId || !!busyAction}
            title="Reject mission"
            onClick={() => updateStatus('Reject', 'aborted')}>
            <XCircle size={14} /> <span className="da-plan-btn-label">{busyAction === 'Reject' ? 'Rejecting...' : 'Reject'}</span>
          </button>
        </div>
      </header>

      {actionErr && <div className="da-plan-action-error" role="alert">{actionErr}</div>}

      <div className="da-plan-body flex min-h-0 flex-1 overflow-hidden">
        {editorOpen && (
          <aside className="da-plan-editor min-h-0 shrink-0 overflow-hidden">
            <MissionEditor />
          </aside>
        )}

        <main className="da-plan-map relative min-h-0 min-w-0 flex-1 overflow-hidden">
          <MapCanvas onFleetAssign={() => setShowFleetAssign(true)} />
        </main>

        {liveOpsOpen && (
          <aside className="da-plan-liveops min-h-0 shrink-0 overflow-hidden">
            <LiveOpsPanel />
          </aside>
        )}
      </div>

      {showFleetAssign && <FleetAssignModal onClose={() => setShowFleetAssign(false)} />}
    </div>
  )
}
