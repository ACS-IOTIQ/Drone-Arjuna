import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Send, XCircle } from 'lucide-react'
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

  return (
    <div className="da-plan-layout flex h-full overflow-x-auto overflow-y-hidden">
      <div className="da-plan-editor shrink-0 overflow-y-auto">
        <MissionEditor />
      </div>

      <div className="da-plan-map relative min-w-0 flex-1 overflow-hidden">
        <MapCanvas onFleetAssign={() => setShowFleetAssign(true)} />
        <div className="da-plan-actions absolute bottom-3 left-3 z-[1000] da-card flex max-w-[calc(100%-180px)] flex-wrap items-center gap-2 px-3 py-2">
          <div className="mr-1 min-w-[150px]">
            <div className="text-[10px] uppercase font-semibold" style={{ color: '#64748b' }}>Active Mission</div>
            <div className="text-xs font-semibold truncate">
              {activeMission ? `${activeMission.name} - ${activeMission.status}` : 'Save or load a mission'}
            </div>
            {actionErr && <div className="text-[10px]" style={{ color: '#dc2626' }}>{actionErr}</div>}
          </div>
          <button
            className="da-btn da-btn-ghost"
            disabled={!activeMissionId || !!busyAction}
            onClick={() => updateStatus('Submit', 'planning')}>
            <Send size={14} /> {busyAction === 'Submit' ? 'Submitting...' : 'Submit'}
          </button>
          <button
            className="da-btn da-btn-success"
            disabled={!activeMissionId || !!busyAction}
            onClick={() => updateStatus('Approve', 'approved')}>
            <CheckCircle2 size={14} /> {busyAction === 'Approve' ? 'Approving...' : 'Approve'}
          </button>
          <button
            className="da-btn da-btn-danger"
            disabled={!activeMissionId || !!busyAction}
            onClick={() => updateStatus('Reject', 'aborted')}>
            <XCircle size={14} /> {busyAction === 'Reject' ? 'Rejecting...' : 'Reject'}
          </button>
        </div>
      </div>

      <div className="da-plan-liveops shrink-0 overflow-y-auto">
        <LiveOpsPanel />
      </div>

      {showFleetAssign && <FleetAssignModal onClose={() => setShowFleetAssign(false)} />}
    </div>
  )
}
