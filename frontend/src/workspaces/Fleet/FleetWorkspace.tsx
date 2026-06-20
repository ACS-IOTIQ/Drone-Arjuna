// ═══════════════════════════════════════════
// FleetWorkspace.tsx
// ═══════════════════════════════════════════
import { useEffect, useState } from 'react'
import { Plus, RefreshCw, Anchor, Package } from 'lucide-react'
import { useFleetStore } from '@/store/fleetStore'
import { useTelemetryStore } from '@/store/telemetryStore'
import { useVesselStore } from '@/store/vesselStore'
import { payloadApi, type PayloadType } from '@/api/payload'
import DroneCard from './DroneCard'
import ConnectModal from './ConnectModal'

const PAYLOAD_CACHE_KEY = 'da_payload_types_fallback'
const PAYLOAD_ASSIGNMENT_KEY = 'da_payload_assignments'

function readCachedPayloads(): PayloadType[] {
  try {
    return JSON.parse(localStorage.getItem(PAYLOAD_CACHE_KEY) || '[]')
  } catch {
    return []
  }
}

function readAssignments(): Record<number, number | null> {
  try {
    return JSON.parse(localStorage.getItem(PAYLOAD_ASSIGNMENT_KEY) || '{}')
  } catch {
    return {}
  }
}

export default function FleetWorkspace() {
  const { instances, connections, fetchInstances, fetchConnections } = useFleetStore()
  const subscribe = useTelemetryStore(s => s.subscribe)
  const { vessels, fetchVessels } = useVesselStore()
  const [showConnect, setShowConnect] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [payloads, setPayloads] = useState<PayloadType[]>([])
  const [payloadAssignments, setPayloadAssignments] = useState<Record<number, number | null>>({})
  const [payloadErr, setPayloadErr] = useState('')

  const refresh = async () => {
    setRefreshing(true)
    await Promise.all([fetchInstances(), fetchConnections(), fetchVessels(), fetchPayloads()])
    setRefreshing(false)
  }

  const fetchPayloads = async () => {
    setPayloadErr('')
    try {
      const { data } = await payloadApi.listTypes()
      setPayloads(data)
    } catch {
      setPayloads(readCachedPayloads())
      setPayloadErr('Payload API unavailable; showing cached payloads.')
    }
  }

  useEffect(() => {
    setPayloadAssignments(readAssignments())
    refresh()
  }, [])

  // Subscribe to telemetry for connected drones
  useEffect(() => {
    instances.forEach(d => {
      if (connections[d.id]?.connected) subscribe(d.id)
    })
  }, [connections, instances])

  // Build vessel lookup by id for card rendering
  const vesselById = Object.fromEntries(vessels.map(v => [v.id, v]))

  const payloadById = Object.fromEntries(payloads.filter(p => p.id != null).map(p => [p.id!, p]))

  const assignPayload = async (droneId: number, payloadId: number | null) => {
    const previous = payloadAssignments
    const next = { ...payloadAssignments, [droneId]: payloadId }
    setPayloadAssignments(next)
    localStorage.setItem(PAYLOAD_ASSIGNMENT_KEY, JSON.stringify(next))
    setPayloadErr('')

    try {
      await payloadApi.assignToDrone(droneId, payloadId)
    } catch (e: any) {
      setPayloadErr(e.response?.data?.detail ?? 'Payload assignment saved locally; backend route is not reachable.')
      setPayloadAssignments(next || previous)
    }
  }

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

      {/* Payload assignment */}
      <div className="mb-5">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: '#475569' }}>
            Payload Assignment
          </h3>
          {payloadErr && <span className="text-[11px]" style={{ color: '#d97706' }}>{payloadErr}</span>}
        </div>
        <div className="da-card overflow-hidden">
          {instances.length === 0 ? (
            <p className="text-xs px-4 py-3" style={{ color: '#64748b' }}>Register drones before assigning payloads.</p>
          ) : (
            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
              {instances.map(d => {
                const assigned = payloadAssignments[d.id]
                const payload = assigned ? payloadById[assigned] : null
                return (
                  <div key={d.id} className="flex items-center gap-3 p-3" style={{ borderRight: '1px solid var(--da-border)', borderBottom: '1px solid var(--da-border)' }}>
                    <Package size={15} style={{ color: payload ? '#0f766e' : '#64748b', flexShrink: 0 }} />
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-semibold">{d.call_sign}</div>
                      <select
                        className="da-input mt-1"
                        value={assigned ?? ''}
                        onChange={e => assignPayload(d.id, e.target.value ? Number(e.target.value) : null)}>
                        <option value="">No payload mounted</option>
                        {payloads.map(p => (
                          <option key={p.id ?? p.name} value={p.id}>
                            {p.name} - {p.category} ({p.weight_kg} kg)
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

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
              payloadName={
                payloadAssignments[d.id] && payloadById[payloadAssignments[d.id]!]
                  ? payloadById[payloadAssignments[d.id]!]!.name
                  : undefined
              }
            />
          ))}
        </div>
      )}

      {showConnect && <ConnectModal onClose={() => setShowConnect(false)} />}
    </div>
  )
}

