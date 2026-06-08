// ═══════════════════════════════════════════
// FleetWorkspace.tsx
// ═══════════════════════════════════════════
import { useEffect, useState } from 'react'
import { Plus, RefreshCw, Anchor } from 'lucide-react'
import { useFleetStore } from '@/store/fleetStore'
import { useTelemetryStore } from '@/store/telemetryStore'
import { useVesselStore } from '@/store/vesselStore'
import DroneCard from './DroneCard'
import ConnectModal from './ConnectModal'

export default function FleetWorkspace() {
  const { instances, connections, fetchInstances, fetchConnections } = useFleetStore()
  const subscribe = useTelemetryStore(s => s.subscribe)
  const { vessels, fetchVessels } = useVesselStore()
  const [showConnect, setShowConnect] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const refresh = async () => {
    setRefreshing(true)
    await Promise.all([fetchInstances(), fetchConnections(), fetchVessels()])
    setRefreshing(false)
  }

  useEffect(() => { refresh() }, [])

  // Subscribe to telemetry for connected drones
  useEffect(() => {
    instances.forEach(d => {
      if (connections[d.id]?.connected) subscribe(d.id)
    })
  }, [connections, instances])

  // Build vessel lookup by id for card rendering
  const vesselById = Object.fromEntries(vessels.map(v => [v.id, v]))

  return (
    <div className="h-full flex flex-col p-5 overflow-auto">
      {/* Header row */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-lg font-semibold">Fleet Overview</h2>
          <p className="text-xs mt-0.5" style={{ color: '#6b7280' }}>
            {instances.length} registered · {Object.values(connections).filter(Boolean).length} connected
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={refresh} className="da-btn da-btn-ghost">
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
            Refresh
          </button>
          <button onClick={() => setShowConnect(true)} className="da-btn da-btn-primary">
            <Plus size={14} /> Connect Drone
          </button>
        </div>
      </div>

      {/* Summary bar */}
      <div className="grid grid-cols-5 gap-3 mb-5">
        {[
          { label: 'Registered',  val: instances.length,    color: '#3b82f6' },
          { label: 'Connected',   val: Object.values(connections).filter(c => c.connected).length, color: '#22c55e' },
          { label: 'Offline',     val: instances.length - Object.values(connections).filter(c => c.connected).length, color: '#6b7280' },
          { label: 'Vessels',     val: vessels.length,      color: '#06b6d4' },
          { label: 'Alerts',      val: 0,                   color: '#f59e0b' },
        ].map(s => (
          <div key={s.label} className="da-card px-4 py-3 flex flex-col gap-1">
            <span className="text-2xl font-bold mono" style={{ color: s.color }}>{s.val}</span>
            <span className="text-xs" style={{ color: '#6b7280' }}>{s.label}</span>
          </div>
        ))}
      </div>

      {/* Naval vessels strip */}
      {vessels.length > 0 && (
        <div className="mb-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: '#9ca3af' }}>
            Naval Vessels
          </h3>
          <div className="flex gap-3 flex-wrap">
            {vessels.map(v => (
              <div key={v.id} className="da-card px-4 py-2 flex items-center gap-3 min-w-[220px]">
                <Anchor size={16} style={{ color: '#06b6d4', flexShrink: 0 }} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold truncate">{v.vessel_id}</div>
                  <div className="text-xs truncate" style={{ color: '#6b7280' }}>{v.name}</div>
                </div>
                <div className="flex flex-col items-end gap-0.5">
                  <span
                    className="text-xs font-medium px-1.5 py-0.5 rounded"
                    style={{
                      background: v.deck_status === 'clear' ? '#14532d' : v.deck_status === 'occupied' ? '#7c2d12' : '#3b2d06',
                      color: v.deck_status === 'clear' ? '#86efac' : v.deck_status === 'occupied' ? '#fca5a5' : '#fde68a',
                    }}
                  >
                    {v.deck_status}
                  </span>
                  {v.latitude != null && (
                    <span className="text-xs mono" style={{ color: '#6b7280' }}>
                      {v.heading_deg != null ? `${v.heading_deg.toFixed(0)}° ` : ''}
                      {v.speed_kts != null ? `${v.speed_kts.toFixed(1)} kts` : ''}
                    </span>
                  )}
                  {v.latitude == null && (
                    <span className="text-xs" style={{ color: '#f59e0b' }}>no position</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Drone grid */}
      {instances.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3"
          style={{ color: '#374151' }}>
          <Plus size={40} style={{ opacity: 0.3 }} />
          <p className="text-sm">No drones registered. Add one in Settings → Master Data.</p>
        </div>
      ) : (
        <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
          {instances.map(d => (
            <DroneCard
              key={d.id}
              drone={d}
              connected={!!connections[d.id]?.connected}
              homeVessel={d.home_vessel_id != null ? vesselById[d.home_vessel_id] : undefined}
              connectionInfo={connections[d.id]}
            />
          ))}
        </div>
      )}

      {showConnect && <ConnectModal onClose={() => setShowConnect(false)} />}
    </div>
  )
}

