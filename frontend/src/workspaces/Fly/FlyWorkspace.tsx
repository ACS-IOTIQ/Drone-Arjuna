import { useEffect, useMemo, useState } from 'react'
import { Activity, Gamepad2, Gauge, Plus, SlidersHorizontal, X } from 'lucide-react'
import { useFleetStore } from '@/store/fleetStore'
import { useTelemetryStore } from '@/store/telemetryStore'
import { droneControlApi } from '@/api/droneControl'
import LiveMap from './LiveMap'
import InstrumentHUD from './InstrumentHUD'
import CommandPanel from './CommandPanel'
import ManualControlPanel from './ManualControlPanel'
import SimLaunchPanel from './SimLaunchPanel'
import SimProgressOverlay from './SimProgressOverlay'

type FlightPanel = 'telemetry' | 'commands' | 'manual'

const PANEL_LABELS: Record<FlightPanel, string> = {
  telemetry: 'Flight instruments',
  commands: 'Flight commands',
  manual: 'Manual control',
}

export default function FlyWorkspace() {
  const { instances, connections, fetchConnections, fetchInstances, startConnectionPolling, stopConnectionPolling } = useFleetStore()
  const { subscribe, clearDrone, frames } = useTelemetryStore()

  const [selectedDroneId, setSelectedDroneId] = useState<number | null>(null)
  const [activePanel, setActivePanel] = useState<FlightPanel | null>(null)
  const [showLauncher, setShowLauncher] = useState(false)
  const [hasEverSimulated, setHasEverSimulated] = useState(false)

  useEffect(() => {
    fetchInstances()
    fetchConnections()
    startConnectionPolling()
    return () => stopConnectionPolling()
  }, [])

  const connectedDrones = useMemo(
    () => instances.filter(
      drone => connections[drone.id]?.connected,
    ),
    [instances, connections],
  )
  const simulationDrones = useMemo(
    () => connectedDrones.filter(drone => connections[drone.id]?.transport === 'simulation'),
    [connectedDrones, connections],
  )
  const connectedDroneIds = useMemo(
    () => new Set(connectedDrones.map(drone => drone.id)),
    [connectedDrones],
  )
  const selectedConnectedDroneExists = connectedDrones.some(drone => drone.id === selectedDroneId)
  const activeDroneId = selectedConnectedDroneExists ? selectedDroneId : connectedDrones[0]?.id ?? null
  const manualShiftAlert = useMemo(
    () => simulationDrones
      .map(drone => ({ drone, frame: frames[drone.id] }))
      .find(({ drone, frame }) => {
        if (!frame?.manual_control_required || !frame?.proximity_alert) return false
        if (frame.proximity_intruder_drone_id == null) return false
        if (frame.proximity_intruder_drone_id === drone.id) return false
        return connectedDroneIds.has(frame.proximity_intruder_drone_id)
      }) ?? null,
    [simulationDrones, connectedDroneIds, frames],
  )
  const activeConnection = activeDroneId ? connections[activeDroneId] : null
  const isSimulated = activeConnection?.transport === 'simulation'
  const activeDrone = instances.find(drone => drone.id === activeDroneId) ?? null

  useEffect(() => {
    if (simulationDrones.length > 0) setHasEverSimulated(true)
  }, [simulationDrones.length])

  // Connection polling can briefly miss a simulation transition (for example
  // while the backend is busy). Check the simulator's authoritative status
  // while a simulated drone is selected so a naturally completed flight
  // cannot leave the workspace stuck on a dead connection.
  useEffect(() => {
    if (!isSimulated || !activeDroneId) return
    let cancelled = false
    const checkSimulation = async () => {
      try {
        const { data } = await droneControlApi.simulateStatus(activeDroneId)
        if (cancelled || data?.active) return
        clearDrone(activeDroneId)
        await fetchConnections()
        if (!cancelled) {
          setSelectedDroneId(null)
          setActivePanel(null)
        }
      } catch {
        // The regular connection poll and telemetry reconnect handle transient failures.
      }
    }
    void checkSimulation()
    const timer = window.setInterval(() => { void checkSimulation() }, 3000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [isSimulated, activeDroneId, clearDrone, fetchConnections])

  useEffect(() => {
    // Deliberately no unsubscribe on unmount/dep-change - telemetry sockets
    // are shared app-wide and should survive workspace switches.
    connectedDrones.forEach(drone => subscribe(drone.id))
  }, [connectedDrones.map(drone => drone.id).join(',')])

  useEffect(() => {
    setActivePanel(activeDroneId ? 'telemetry' : null)
  }, [activeDroneId])

  const handleSimStopped = async () => {
    if (activeDroneId) clearDrone(activeDroneId)
    await fetchConnections()
    setSelectedDroneId(null)
    setActivePanel(null)
  }

  const handleSimStarted = async (droneId: number) => {
    subscribe(droneId)
    setSelectedDroneId(droneId)
    await fetchInstances()
    await fetchConnections()
    setShowLauncher(false)
  }

  const launcherVisible = (!activeDroneId && !hasEverSimulated) || showLauncher

  const togglePanel = (panel: FlightPanel) => {
    setActivePanel(current => current === panel ? null : panel)
  }

  const handleManualShift = (droneId: number) => {
    setSelectedDroneId(droneId)
    setActivePanel('manual')
  }

  return (
    <div className={`da-fly-workspace ${activePanel ? 'control-open' : ''}`}>
      <header className="da-fly-header">
        <div className="da-fly-drone-strip" aria-label="Connected drones">
          {connectedDrones.length === 0 ? (
            <div className="da-fly-no-drone"><Activity size={14} /> No connected drones</div>
          ) : (
            connectedDrones.map(drone => (
              <button
                key={drone.id}
                type="button"
                className={drone.id === activeDroneId ? 'da-fly-drone is-active' : 'da-fly-drone'}
                onClick={() => setSelectedDroneId(drone.id)}>
                <span>{drone.call_sign}</span>
                <b>{connections[drone.id]?.transport === 'simulation' ? 'SIM' : 'GPS'}</b>
              </button>
            ))
          )}
        </div>

        <div className="da-fly-header-actions">
          <button
            type="button"
            className="da-fly-header-btn"
            onClick={() => setShowLauncher(true)}
            title="Launch another simulation">
            <Plus size={15} /><span>Simulation</span>
          </button>

          {activeDroneId && (
            <>
              <span className="da-fly-header-divider" />
              <button
                type="button"
                className={activePanel === 'telemetry' ? 'da-fly-header-btn is-active' : 'da-fly-header-btn'}
                onClick={() => togglePanel('telemetry')}
                title="Flight instruments"
                aria-pressed={activePanel === 'telemetry'}>
                <Gauge size={15} /><span>Instruments</span>
              </button>
              <button
                type="button"
                className={activePanel === 'commands' ? 'da-fly-header-btn is-active' : 'da-fly-header-btn'}
                onClick={() => togglePanel('commands')}
                title="Flight commands"
                aria-pressed={activePanel === 'commands'}>
                <SlidersHorizontal size={15} /><span>Commands</span>
              </button>
              <button
                type="button"
                className={activePanel === 'manual' ? 'da-fly-header-btn is-active' : 'da-fly-header-btn'}
                onClick={() => togglePanel('manual')}
                title="Manual control"
                aria-pressed={activePanel === 'manual'}>
                <Gamepad2 size={15} /><span>Manual</span>
              </button>
            </>
          )}
        </div>
      </header>

      <div className="da-fly-body">
        <main className="da-fly-map-stage">
          {manualShiftAlert && (
            <div className="mx-4 mt-4 rounded-2xl border border-red-300 bg-red-50/95 px-4 py-3 text-sm text-red-950 shadow-sm">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <strong>Shift to manual control</strong>
                  <div>
                    {manualShiftAlert.drone.call_sign} is within{' '}
                    {manualShiftAlert.frame?.proximity_distance_m?.toFixed(1) ?? '250.0'} m of Drone #
                    {manualShiftAlert.frame?.proximity_intruder_drone_id ?? 'unknown'}.
                  </div>
                </div>
                <button
                  type="button"
                  className="da-btn da-btn-danger justify-center"
                  onClick={() => handleManualShift(manualShiftAlert.drone.id)}>
                  Shift to manual control
                </button>
              </div>
            </div>
          )}
          <LiveMap
            droneId={activeDroneId}
            onSelectDrone={setSelectedDroneId}
            onManualControlRequest={() => activeDroneId && handleManualShift(activeDroneId)}
          />
        </main>

        {activeDroneId && activePanel && (
          <aside className="da-fly-control-panel" aria-label={PANEL_LABELS[activePanel]}>
            <header>
              <div className="min-w-0">
                <strong>{PANEL_LABELS[activePanel]}</strong>
                <span>{activeDrone?.call_sign ?? `Drone #${activeDroneId}`}{isSimulated ? ' / Simulation' : ''}</span>
              </div>
              <button type="button" onClick={() => setActivePanel(null)} title="Close flight panel">
                <X size={16} />
              </button>
            </header>
            <div className="da-fly-control-scroll">
              {activePanel === 'telemetry' && <InstrumentHUD droneId={activeDroneId} />}
              {activePanel === 'commands' && <CommandPanel droneId={activeDroneId} />}
              {activePanel === 'manual' && <ManualControlPanel droneId={activeDroneId} />}
            </div>
          </aside>
        )}
      </div>

      {isSimulated && activeDroneId && !launcherVisible && (
        <SimProgressOverlay droneId={activeDroneId} onStopped={handleSimStopped} />
      )}

      {launcherVisible && (
        <SimLaunchPanel
          onStarted={handleSimStarted}
          onClose={activeDroneId || hasEverSimulated ? () => setShowLauncher(false) : undefined}
        />
      )}
    </div>
  )
}
