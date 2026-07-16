// ═══════════════════════════════════════════════════════════════
// src/components/layout/AppShell.tsx
// ═══════════════════════════════════════════════════════════════
import { useState } from 'react'
import Sidebar              from './Sidebar'
import TopBar               from './TopBar'
import NotificationDrawer   from '@/components/common/NotificationDrawer'
import CameraWindow         from '@/components/common/CameraWindow'
import ErrorBoundary        from '@/components/common/ErrorBoundary'
import FleetWorkspace       from '@/workspaces/Fleet/FleetWorkspace'
import PlanWorkspace        from '@/workspaces/Plan/PlanWorkspace'
import FlyWorkspace         from '@/workspaces/Fly/FlyWorkspace'
import MonitorWorkspace     from '@/workspaces/Monitor/MonitorWorkspace'
import SettingsWorkspace    from '@/workspaces/Settings/SettingsWorkspace'

export type Workspace = 'fleet' | 'plan' | 'fly' | 'monitor' | 'settings'

const WORKSPACES: Record<Workspace, JSX.Element> = {
  fleet:    <FleetWorkspace />,
  plan:     <PlanWorkspace />,
  fly:      <FlyWorkspace />,
  monitor:  <MonitorWorkspace />,
  settings: <SettingsWorkspace />,
}

export default function AppShell() {
  const [active, setActive]       = useState<Workspace>('fleet')
  const [notifOpen, setNotif]     = useState(false)
  const [cameraOpen, setCameraOpen] = useState(false)

  return (
    <div className="da-app-shell flex h-screen w-screen flex-col overflow-hidden">
      <TopBar workspace={active} onNotifClick={() => setNotif(v => !v)} />
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <Sidebar
          active={active}
          onSelect={setActive}
          cameraOpen={cameraOpen}
          onCameraToggle={() => setCameraOpen(v => !v)}
        />
        <main className="relative min-w-0 flex-1 overflow-hidden">
          <ErrorBoundary key={active}>
            {WORKSPACES[active]}
          </ErrorBoundary>
        </main>
      </div>
      <NotificationDrawer open={notifOpen} onClose={() => setNotif(false)} />

      {/* Floating camera overlay — rendered at AppShell level so it persists
          across workspace switches and stays above all other content */}
      <CameraWindow visible={cameraOpen} onClose={() => setCameraOpen(false)} />
    </div>
  )
}
