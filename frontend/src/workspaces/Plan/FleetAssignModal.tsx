// ═══════════════════════════════════════════════════════════════
// src/workspaces/Plan/FleetAssignModal.tsx
// Multi-drone -> target assignment ("Q-SWARM" fleet optimizer).
// Picks from currently-connected drones, lets the operator enter
// target coordinates, and solves the assignment either exactly
// (OR-Tools, default) or via an experimental QAOA quantum solver.
// ═══════════════════════════════════════════════════════════════
import { useState } from 'react'
import { X, Plus, Trash2, Atom, Cpu, Loader2 } from 'lucide-react'
import { useFleetStore } from '@/store/fleetStore'
import { droneFlightApi, type FleetTarget, type FleetAssignResult } from '@/api/droneFlight'

interface Props { onClose: () => void }

let nextTargetSeq = 1

export default function FleetAssignModal({ onClose }: Props) {
  const { instances, connections } = useFleetStore()
  const connectedDrones = instances.filter(d => connections[d.id]?.connected)

  const [selectedIds, setSelectedIds] = useState<number[]>(() => connectedDrones.map(d => d.id))
  const [targets, setTargets] = useState<FleetTarget[]>([
    { id: `T${nextTargetSeq++}`, lat: 17.385, lon: 78.4867 },
  ])
  const [useQuantum, setUseQuantum] = useState(false)
  const [qubitBudget, setQubitBudget] = useState(12)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [result, setResult] = useState<FleetAssignResult | null>(null)

  const toggleDrone = (id: number) => {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  const addTarget = () => {
    setTargets(prev => [...prev, { id: `T${nextTargetSeq++}`, lat: 17.385, lon: 78.4867 }])
  }

  const updateTarget = (idx: number, patch: Partial<FleetTarget>) => {
    setTargets(prev => prev.map((t, i) => i === idx ? { ...t, ...patch } : t))
  }

  const removeTarget = (idx: number) => {
    setTargets(prev => prev.filter((_, i) => i !== idx))
  }

  const runAssignment = async () => {
    setLoading(true); setErr(''); setResult(null)
    try {
      const { data } = await droneFlightApi.assignFleet({
        drone_instance_ids: selectedIds.length ? selectedIds : undefined,
        targets,
        use_quantum: useQuantum,
        qubit_budget: qubitBudget,
      })
      setResult(data)
    } catch (e: any) {
      setErr(e.response?.data?.detail ?? 'Fleet assignment failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.7)', zIndex: 2000 }} onClick={onClose}>
      <div className="da-card w-full max-w-lg p-6" onClick={e => e.stopPropagation()}
        style={{ maxHeight: '90vh', overflowY: 'auto' }}>

        <div className="flex items-center justify-between mb-5">
          <h3 className="font-semibold flex items-center gap-2">
            <Cpu size={16} style={{ color: 'var(--da-teal)' }} /> Fleet Assignment
          </h3>
          <button onClick={onClose}><X size={16} style={{ color: '#6b7280' }} /></button>
        </div>

        {/* Drone selection */}
        <div className="mb-4">
          <span className="text-xs" style={{ color: '#64748b' }}>CONNECTED DRONES</span>
          {connectedDrones.length === 0 ? (
            <p className="text-[11px] mt-1" style={{ color: '#4b5563' }}>
              No drones connected. Connect from the Fleet workspace first.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2 mt-1">
              {connectedDrones.map(d => (
                <label key={d.id}
                  className="flex items-center gap-1.5 px-2 py-1 rounded text-xs cursor-pointer"
                  style={{
                    border: `1px solid ${selectedIds.includes(d.id) ? 'var(--da-teal)' : 'var(--da-border)'}`,
                    color: selectedIds.includes(d.id) ? 'var(--da-teal)' : '#94a3b8',
                  }}>
                  <input type="checkbox" checked={selectedIds.includes(d.id)}
                    onChange={() => toggleDrone(d.id)} />
                  {d.call_sign}
                </label>
              ))}
            </div>
          )}
        </div>

        {/* Targets */}
        <div className="mb-4">
          <div className="flex items-center justify-between">
            <span className="text-xs" style={{ color: '#64748b' }}>TARGETS</span>
            <button className="da-btn da-btn-ghost text-[10px] px-2 py-1" onClick={addTarget}>
              <Plus size={12} /> Add target
            </button>
          </div>
          <div className="flex flex-col gap-2 mt-2">
            {targets.map((t, idx) => (
              <div key={idx} className="grid gap-2 items-center" style={{ gridTemplateColumns: '70px 1fr 1fr 28px' }}>
                <input className="da-input mono text-[11px]" value={t.id}
                  onChange={e => updateTarget(idx, { id: e.target.value })} />
                <input type="number" step="0.0001" className="da-input mono text-[11px]" value={t.lat}
                  onChange={e => updateTarget(idx, { lat: Number(e.target.value) })} placeholder="lat" />
                <input type="number" step="0.0001" className="da-input mono text-[11px]" value={t.lon}
                  onChange={e => updateTarget(idx, { lon: Number(e.target.value) })} placeholder="lon" />
                <button onClick={() => removeTarget(idx)} disabled={targets.length === 1}>
                  <Trash2 size={13} style={{ color: targets.length === 1 ? '#374151' : '#ef4444' }} />
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Solver selection */}
        <div className="mb-4 p-3 rounded" style={{ border: '1px solid var(--da-border)' }}>
          <label className="flex items-center gap-2 text-xs cursor-pointer" style={{ color: '#94a3b8' }}>
            <input type="checkbox" checked={useQuantum} onChange={e => setUseQuantum(e.target.checked)} />
            <Atom size={13} style={{ color: useQuantum ? '#a855f7' : '#64748b' }} />
            Use quantum solver (QAOA on Qiskit Aer) — experimental
          </label>
          {useQuantum && (
            <label className="flex items-center gap-2 mt-2 text-xs" style={{ color: '#94a3b8' }}>
              Qubit budget per sub-problem
              <input type="number" min={2} max={20} className="da-input mono text-[11px]" style={{ width: 70 }}
                value={qubitBudget} onChange={e => setQubitBudget(Number(e.target.value))} />
            </label>
          )}
          {!useQuantum && (
            <p className="text-[10px] mt-1" style={{ color: '#4b5563' }}>
              Default: exact OR-Tools CP-SAT solve, no qubit limits.
            </p>
          )}
        </div>

        {err && (
          <p className="text-xs px-3 py-2 rounded mb-3"
            style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>{err}</p>
        )}

        {/* Results */}
        {result && (
          <div className="mb-4 rounded" style={{ border: '1px solid var(--da-border)' }}>
            <div className="flex items-center justify-between px-3 py-2 flex-wrap gap-1"
              style={{ borderBottom: '1px solid var(--da-border)', background: 'rgba(255,255,255,0.02)' }}>
              <span className="text-[11px] font-semibold" style={{ color: 'var(--da-teal)' }}>
                {result.solver}
              </span>
              <span className="text-[10px] mono" style={{ color: '#94a3b8' }}>
                {(result.total_distance_m / 1000).toFixed(2)} km total
                {result.num_subproblems > 1 ? ` · ${result.num_subproblems} sub-problems` : ''}
              </span>
              <span className={`da-chip ${result.all_feasible ? 'ok' : 'danger'}`}>
                <span className="da-chip-dot" />
                {result.all_feasible ? 'Feasible' : 'Infeasible'}
              </span>
            </div>
            {result.assignments.map((a, i) => (
              <div key={i} className="flex items-center justify-between px-3 py-1.5 text-[11px]"
                style={{ borderBottom: i < result.assignments.length - 1 ? '1px solid var(--da-border)' : 'none' }}>
                <span className="mono" style={{ color: '#e2e8f0' }}>{a.call_sign ?? a.drone_instance_id}</span>
                <span style={{ color: '#4b5563' }}>→</span>
                <span className="mono" style={{ color: '#94a3b8' }}>{a.target_id}</span>
                <span className="mono" style={{ color: '#64748b' }}>{(a.distance_m / 1000).toFixed(2)} km</span>
              </div>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          <button className="da-btn da-btn-ghost flex-1" onClick={onClose}>Close</button>
          <button className="da-btn da-btn-primary flex-1" onClick={runAssignment}
            disabled={loading || connectedDrones.length === 0 || targets.length === 0}>
            {loading ? <><Loader2 size={14} className="animate-spin" /> Solving…</> : 'Run Assignment'}
          </button>
        </div>
      </div>
    </div>
  )
}
