// ═══════════════════════════════════════════
// FlyWorkspace.tsx
// ═══════════════════════════════════════════
import { useEffect, useState } from 'react'
import { Gamepad2, Plus } from 'lucide-react'
import { useFleetStore } from '@/store/fleetStore'
import { useTelemetryStore } from '@/store/telemetryStore'
import LiveMap from './LiveMap'
import InstrumentHUD from './InstrumentHUD'
import CommandPanel from './CommandPanel'
import ManualControlPanel from './ManualControlPanel'
import SimLaunchPanel from './SimLaunchPanel'
import SimProgressOverlay from './SimProgressOverlay'

export default function FlyWorkspace() {
  const { instances, connections, fetchConnections, fetchInstances } = useFleetStore()
  const { subscribe, unsubscribe } = useTelemetryStore()

  const [selectedDroneId, setSelectedDroneId] = useState<number | null>(null)
  const [manualOpen, setManualOpen]           = useState(false)
  const [showLauncher, setShowLauncher]       = useState(false)

  // Load instances + connections on mount, poll every 5 s
  useEffect(() => {
    fetchInstances()
    fetchConnections()
    const poll = setInterval(fetchConnections, 5000)
    return () => clearInterval(poll)
  }, [])

  const connectedDrones = instances.filter(d => connections[d.id])
  const activeDroneId   = selectedDroneId ?? connectedDrones[0]?.id ?? null

  // Subscribe to telemetry for every connected drone (not just the active one)
  // so the map can render the whole fleet flying simultaneously.
  useEffect(() => {
    connectedDrones.forEach(d => subscribe(d.id))
    return () => connectedDrones.forEach(d => unsubscribe(d.id))
  }, [connectedDrones.map(d => d.id).join(',')])

  const activeConnection = activeDroneId ? connections[activeDroneId] : null
  const isSimulated      = (activeConnection as any)?.transport === 'simulation'

  const handleSimStopped = async () => {
    await fetchConnections()
    setSelectedDroneId(null)
    setManualOpen(false)
  }

  const handleSimStarted = () => {
    fetchConnections()
    setShowLauncher(false)
  }

  const launcherVisible = !activeDroneId || showLauncher

  return (
    <div className="h-full flex flex-col overflow-hidden">

      {/* ── Drone selector strip (multi-drone) ── */}
      {connectedDrones.length > 0 && (
        <div className="flex items-center gap-1 px-3 py-1.5 shrink-0"
          style={{ background: 'var(--da-surface)', borderBottom: '1px solid var(--da-border)' }}>
          {connectedDrones.length > 1 && (
            <span className="text-xs mr-2" style={{ color: '#6b7280' }}>Viewing:</span>
          )}
          {connectedDrones.map(d => {
            const conn = connections[d.id] as any
            const sim  = conn?.transport === 'simulation'
            return (
              <button key={d.id}
                onClick={() => setSelectedDroneId(d.id)}
                className="da-btn text-xs py-1 px-3 flex items-center gap-1.5"
                style={{
                  background: d.id === activeDroneId ? 'rgba(59,130,246,0.2)' : 'transparent',
                  color:      d.id === activeDroneId ? '#3b82f6' : '#6b7280',
                  border: `1px solid ${d.id === activeDroneId ? '#3b82f6' : 'var(--da-border)'}`,
                }}>
                {d.call_sign}
                {sim && (
                  <span className="text-[9px] font-bold px-1 rounded"
                    style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e' }}>SIM</span>
                )}
              </button>
            )
          })}
          <button
            onClick={() => setShowLauncher(true)}
            className="da-btn da-btn-ghost text-xs py-1 px-2 flex items-center gap-1 ml-1"
            title="Launch another simulated drone">
            <Plus size={12} /> Add Sim
          </button>
        </div>
      )}

      {/* ── Main content ── */}
      <div className={`relative flex-1 overflow-hidden ${manualOpen ? 'manual-is-open' : ''}`}>
        <LiveMap
          droneId={activeDroneId}
          onSelectDrone={setSelectedDroneId}
          onManualControlRequest={() => setManualOpen(true)}
        />

        {/* HUD — top-left overlay */}
        {activeDroneId && (
          <div className="da-fly-top-overlay">
            <div className="da-fly-overlay-item"><InstrumentHUD droneId={activeDroneId} /></div>
            {isSimulated && (
              <div className="da-fly-sim-badge"><span>SIMULATION MODE</span></div>
            )}
            <div className="da-fly-overlay-item da-fly-command"><CommandPanel droneId={activeDroneId} /></div>
          </div>
        )}

        {/* Command panel — top-right overlay */}
        {/* Manual control — bottom-right overlay, shown when toggled */}
        {activeDroneId && manualOpen && (
          <div className="da-fly-manual-panel absolute bottom-14 right-3 z-[999]">
            <ManualControlPanel droneId={activeDroneId} />
          </div>
        )}

        {/* Manual control toggle button — bottom-right */}
        {activeDroneId && (
          <button
            onClick={() => setManualOpen(v => !v)}
            title={manualOpen ? 'Hide manual control' : 'Show manual control'}
            className="absolute bottom-3 right-3 z-[999] flex items-center gap-1.5 da-btn text-xs"
            style={{
              background: manualOpen
                ? 'rgba(32,208,180,0.18)'
                : 'rgba(255,255,255,0.94)',
              border: `1px solid ${manualOpen ? 'rgba(32,208,180,0.45)' : 'var(--da-border)'}`,
              color: manualOpen ? 'var(--da-teal)' : '#334155',
              backdropFilter: 'blur(8px)',
            }}>
            <Gamepad2 size={13} />
            {manualOpen ? 'Manual ON' : 'Manual'}
          </button>
        )}

        {/* SIM mode banner */}


        {/* Simulation progress bar */}
        {isSimulated && activeDroneId && (
          <SimProgressOverlay droneId={activeDroneId} onStopped={handleSimStopped} />
        )}

        {/* Simulation launcher — first-time (no drones) or opened via "Add Sim" */}
        {launcherVisible && (
          <SimLaunchPanel
            onStarted={handleSimStarted}
            onClose={activeDroneId ? () => setShowLauncher(false) : undefined}
          />
        )}
      </div>
    </div>
  )
}
