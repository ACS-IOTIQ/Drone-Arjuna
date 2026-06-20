import { useEffect, useState } from 'react'
import { Download } from 'lucide-react'
import { useFleetStore } from '@/store/fleetStore'
import { useTelemetryStore, TelemetryFrame } from '@/store/telemetryStore'
import GaugeDashboard from './GaugeDashboard'
import TelemetryChart from './TelemetryChart'
import SystemLog      from './SystemLog'

export default function MonitorWorkspace() {
  const { instances, connections, fetchInstances, fetchConnections } = useFleetStore()
  const { subscribe, unsubscribe } = useTelemetryStore()
  const [selDrone, setSelDrone] = useState<number | null>(null)

  // Fetch data on mount and poll every 5 s for connection changes
  useEffect(() => {
    fetchInstances()
    fetchConnections()
    const poll = setInterval(fetchConnections, 5000)
    return () => clearInterval(poll)
  }, [])

  const connectedIds  = instances.filter(d => connections[d.id]).map(d => d.id)
  const activeDroneId = selDrone ?? connectedIds[0] ?? null

  // Subscribe to live telemetry WebSocket for the active drone
  useEffect(() => {
    if (!activeDroneId) return
    subscribe(activeDroneId)
    return () => unsubscribe(activeDroneId)
  }, [activeDroneId])

  return (
    <div className="h-full flex flex-col p-5 gap-4 overflow-auto">

      {/* Drone selector — only visible when multiple connected */}
      {connectedIds.length > 1 && (
        <div className="flex gap-2">
          {instances.filter(d => connections[d.id]).map(d => (
            <button key={d.id}
              onClick={() => setSelDrone(d.id)}
              className="da-btn text-xs"
              style={{
                background: d.id === activeDroneId ? 'rgba(59,130,246,0.2)' : 'transparent',
                color:      d.id === activeDroneId ? '#3b82f6' : '#6b7280',
                border:     `1px solid ${d.id === activeDroneId ? '#3b82f6' : 'var(--da-border)'}`,
              }}>
              {d.call_sign}
            </button>
          ))}
        </div>
      )}

      {!activeDroneId ? (
        <div className="flex-1 flex items-center justify-center">
          <p style={{ color: '#374151' }}>
            No drones connected. Connect a drone in the Fleet workspace.
          </p>
        </div>
      ) : (
        <>
          <GaugeDashboard droneId={activeDroneId} />
          <TelemetryChart droneId={activeDroneId} />

          {/* Raw telemetry + system log side by side on wide screens */}
          <div className="grid gap-4" style={{ gridTemplateColumns: '1fr 1fr' }}>
            <RawTelemetry droneId={activeDroneId} />
            <SystemLog    droneId={activeDroneId} />
          </div>
        </>
      )}
    </div>
  )
}

function RawTelemetry({ droneId }: { droneId: number }) {
  const frame = useTelemetryStore(s => s.frames[droneId])
  const history = useTelemetryStore(s => s.history[droneId] ?? [])

  const exportCsv = () => {
    const rows = history.length ? history : frame ? [frame] : []
    if (rows.length === 0) return
    const keys = Array.from(new Set(rows.flatMap(row => Object.keys(row)))).sort()
    const escape = (value: unknown) => `"${String(value ?? '').replace(/"/g, '""')}"`
    const csv = [
      keys.join(','),
      ...rows.map(row => keys.map(key => escape((row as any)[key])).join(',')),
    ].join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `drone-${droneId}-telemetry.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="da-card p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">Raw Telemetry</h3>
          <p className="text-[11px]" style={{ color: '#64748b' }}>{history.length} buffered frames</p>
        </div>
        <button className="da-btn da-btn-ghost text-xs" onClick={exportCsv} disabled={!frame && history.length === 0}>
          <Download size={13} /> CSV
        </button>
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-0.5 text-xs mono overflow-auto"
        style={{ maxHeight: 280 }}>
        {frame
          ? Object.entries(frame)
              .filter(([k]) => !['call_sign', 'connected'].includes(k))
              .map(([k, v]) => (
                <div key={k} className="flex justify-between py-0.5"
                  style={{ borderBottom: '1px solid var(--da-border)' }}>
                  <span style={{ color: '#4b5563' }}>{k}</span>
                  <span style={{ color: '#94a3b8' }}>
                    {typeof v === 'number' ? (v as number).toFixed(2) : String(v)}
                  </span>
                </div>
              ))
          : <p style={{ color: '#374151' }}>Waiting for telemetry…</p>
        }
      </div>
    </div>
  )
}
