import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Send, XCircle } from 'lucide-react'
import { useMissionStore } from '@/store/missionStore'
import { useFleetStore } from '@/store/fleetStore'
import { useVesselStore } from '@/store/vesselStore'
import MapCanvas from './MapCanvas'
import MissionEditor from './MissionEditor'
import LiveOpsPanel from './LiveOpsPanel'

export default function PlanWorkspace() {
  const { missions, activeMissionId, fetchMissions, updateMissionStatus } = useMissionStore()
  const fetchInstances = useFleetStore(s => s.fetchInstances)
  const fetchVessels = useVesselStore(s => s.fetchVessels)
  const [busyAction, setBusyAction] = useState('')
  const [actionErr, setActionErr] = useState('')

  useEffect(() => {
    fetchMissions()
    fetchInstances()
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
      setActionErr(e.response?.data?.detail ?? `${label} failed`)
    } finally {
      setBusyAction('')
    }
  }

  return (
    <div className="h-full flex overflow-hidden">
      <div className="shrink-0 overflow-y-auto"
        style={{
          width: 320,
          background: 'var(--da-surface)',
          borderRight: '1px solid var(--da-border)',
        }}>
        <MissionEditor />
      </div>

      <div className="flex-1 relative overflow-hidden">
        <MapCanvas />
        <div className="absolute bottom-3 left-3 z-[1000] da-card px-3 py-2 flex flex-wrap items-center gap-2 max-w-[calc(100%-180px)]">
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

      <div className="shrink-0 overflow-y-auto" style={{ width: 260 }}>
        <LiveOpsPanel />
      </div>
    </div>
  )
}
