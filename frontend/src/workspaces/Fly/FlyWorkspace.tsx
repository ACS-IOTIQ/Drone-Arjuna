// ═══════════════════════════════════════════
// FlyWorkspace.tsx
// ═══════════════════════════════════════════
import { useEffect, useState } from 'react'
import { Gamepad2 } from 'lucide-react'
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

  // Load instances + connections on mount, poll every 5 s
  useEffect(() => {
    fetchInstances()
    fetchConnections()
    const poll = setInterval(fetchConnections, 5000)
    return () => clearInterval(poll)
  }, [])

  const connectedDrones = instances.filter(d => connections[d.id])
  const activeDroneId   = selectedDroneId ?? connectedDrones[0]?.id ?? null

  // Subscribe to telemetry WebSocket when active drone changes
  useEffect(() => {
    if (!activeDroneId) return
    subscribe(activeDroneId)
    return () => unsubscribe(activeDroneId)
  }, [activeDroneId])

  const activeConnection = activeDroneId ? connections[activeDroneId] : null
  const isSimulated      = (activeConnection as any)?.transport === 'simulation'

  const handleSimStopped = async () => {
    await fetchConnections()
    setSelectedDroneId(null)
    setManualOpen(false)
  }

  const handleSimStarted = () => { fetchConnections() }

  return (
    <div className="h-full flex flex-col overflow-hidden">

      {/* ── Drone selector strip (multi-drone) ── */}
      {connectedDrones.length > 1 && (
        <div className="flex items-center gap-1 px-3 py-1.5 shrink-0"
          style={{ background: 'var(--da-surface)', borderBottom: '1px solid var(--da-border)' }}>
          <span className="text-xs mr-2" style={{ color: '#6b7280' }}>Viewing:</span>
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
        </div>
      )}

      {/* ── Main content ── */}
      <div className="flex-1 relative overflow-hidden">
        <LiveMap droneId={activeDroneId} />

        {/* HUD — top-left overlay */}
        {activeDroneId && (
          <div className="absolute top-3 left-3 z-[999]">
            <InstrumentHUD droneId={activeDroneId} />
          </div>
        )}

        {/* Command panel — top-right overlay */}
        {activeDroneId && (
          <div className="absolute top-3 right-3 z-[999]" style={{ width: 220 }}>
            <CommandPanel droneId={activeDroneId} />
          </div>
        )}

        {/* Manual control — bottom-right overlay, shown when toggled */}
        {activeDroneId && manualOpen && (
          <div className="absolute bottom-14 right-3 z-[999]">
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
        {isSimulated && activeDroneId && (
          <div className="absolute top-3 left-1/2 z-[999]"
            style={{ transform: 'translateX(-50%)' }}>
            <span className="px-3 py-1 rounded-full text-[10px] font-bold tracking-widest"
              style={{
                background: 'rgba(34,197,94,0.12)', color: '#22c55e',
                border: '1px solid rgba(34,197,94,0.25)', backdropFilter: 'blur(6px)',
              }}>
              SIMULATION MODE
            </span>
          </div>
        )}

        {/* Simulation progress bar */}
        {isSimulated && activeDroneId && (
          <SimProgressOverlay droneId={activeDroneId} onStopped={handleSimStopped} />
        )}

        {/* No drone — show simulation launcher */}
        {!activeDroneId && (
          <SimLaunchPanel onStarted={handleSimStarted} />
        )}
      </div>
    </div>
  )
}
