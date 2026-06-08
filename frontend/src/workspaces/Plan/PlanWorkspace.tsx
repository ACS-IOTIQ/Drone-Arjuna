// ═══════════════════════════════════════════════════════════════
// src/workspaces/Plan/PlanWorkspace.tsx
// Three-column layout:
//   [MissionEditor 320px] [MapCanvas flex-1] [LiveOpsPanel 260px]
// ═══════════════════════════════════════════════════════════════
import { useEffect } from 'react'
import { useMissionStore } from '@/store/missionStore'
import MapCanvas     from './MapCanvas'
import MissionEditor from './MissionEditor'
import LiveOpsPanel  from './LiveOpsPanel'

export default function PlanWorkspace() {
  const fetchMissions = useMissionStore(s => s.fetchMissions)
  useEffect(() => { fetchMissions() }, [])

  return (
    <div className="h-full flex overflow-hidden">

      {/* Left — Mission editor */}
      <div className="shrink-0 overflow-y-auto"
        style={{
          width: 320,
          background: 'var(--da-surface)',
          borderRight: '1px solid var(--da-border)',
        }}>
        <MissionEditor />
      </div>

      {/* Centre — Interactive map (takes all remaining space) */}
      <div className="flex-1 relative overflow-hidden">
        <MapCanvas />
      </div>

      {/* Right — Live ops panel */}
      <div className="shrink-0 overflow-y-auto"
        style={{ width: 260 }}>
        <LiveOpsPanel />
      </div>

    </div>
  )
}
