import { useEffect, useState } from 'react'
import { Activity, Gamepad2, Gauge, Plus, SlidersHorizontal, X } from 'lucide-react'
import { useFleetStore } from '@/store/fleetStore'
import { useTelemetryStore } from '@/store/telemetryStore'
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
  const { instances, connections, fetchConnections, fetchInstances } = useFleetStore()
  const { subscribe, frames } = useTelemetryStore()

  const [selectedDroneId, setSelectedDroneId] = useState<number | null>(null)
  const [activePanel, setActivePanel] = useState<FlightPanel | null>(null)
  const [showLauncher, setShowLauncher] = useState(false)
  const [hasEverSimulated, setHasEverSimulated] = useState(false)

  useEffect(() => {
    fetchInstances()
    fetchConnections()
    const poll = setInterval(fetchConnections, 5000)
    return () => clearInterval(poll)
  }, [])

  const simulatingDrones = instances.filter(
    drone => connections[drone.id]?.transport === 'simulation',
  )
  const selectedSimulationExists = simulatingDrones.some(drone => drone.id === selectedDroneId)
  const activeDroneId = selectedSimulationExists ? selectedDroneId : simulatingDrones[0]?.id ?? null
  const manualShiftAlert = simulatingDrones
    .map(drone => ({ drone, frame: frames[drone.id] }))
    .find(({ frame }) => frame?.manual_control_required && frame?.proximity_alert) ?? null

  useEffect(() => {
    if (simulatingDrones.length > 0) setHasEverSimulated(true)
  }, [simulatingDrones.length])

  useEffect(() => {
    // Deliberately no unsubscribe on unmount/dep-change - telemetry sockets
    // are shared app-wide and should survive workspace switches.
    simulatingDrones.forEach(drone => subscribe(drone.id))
  }, [simulatingDrones.map(drone => drone.id).join(',')])

  useEffect(() => {
    setActivePanel(activeDroneId ? 'telemetry' : null)
  }, [activeDroneId])

  const activeConnection = activeDroneId ? connections[activeDroneId] : null
  const isSimulated = activeConnection?.transport === 'simulation'
  const activeDrone = instances.find(drone => drone.id === activeDroneId) ?? null

  const handleSimStopped = async () => {
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
        <div className="da-fly-drone-strip" aria-label="Simulating drones">
          {simulatingDrones.length === 0 ? (
            <div className="da-fly-no-drone"><Activity size={14} /> No active simulation</div>
          ) : (
            simulatingDrones.map(drone => (
              <button
                key={drone.id}
                type="button"
                className={drone.id === activeDroneId ? 'da-fly-drone is-active' : 'da-fly-drone'}
                onClick={() => setSelectedDroneId(drone.id)}>
                <span>{drone.call_sign}</span>
                <b>SIM</b>
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
                    {manualShiftAlert.frame?.proximity_distance_m?.toFixed(1) ?? '200.0'} m of Drone #
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
