// ═══════════════════════════════════════════
// DroneInstanceManager.tsx
// ═══════════════════════════════════════════
import { useEffect, useMemo, useState } from 'react'
import { Plus, X, Save, Anchor } from 'lucide-react'
import { droneMasterApi } from '@/api/droneMaster'
import { payloadApi, type PayloadType } from '@/api/payload'
import { vesselApi } from '@/api/vessel'
import { useVesselStore } from '@/store/vesselStore'
import type { NavalVessel } from '@/store/vesselStore'

interface DroneInst {
  id?: number
  call_sign: string
  drone_type_id: number
  serial_number: string
  mavlink_system_id: number
  home_vessel_id: number | ''
  notes: string
}

const BLANK: DroneInst = {
  call_sign: '', drone_type_id: 0,
  serial_number: '', mavlink_system_id: 1,
  home_vessel_id: '', notes: '',
}

export default function DroneInstanceManager() {
  const [drones, setDrones]   = useState<any[]>([])
  const [types, setTypes]     = useState<any[]>([])
  const [payloadTypes, setPayloadTypes] = useState<PayloadType[]>([])
  const [editing, setEditing] = useState<DroneInst | null>(null)
  const [saving, setSaving]   = useState(false)
  const [err, setErr]         = useState('')
  const { vessels, fetchVessels } = useVesselStore()

  const load = async () => {
    const [d, t, p] = await Promise.all([
      droneMasterApi.listDrones(),
      droneMasterApi.listTypes(),
      payloadApi.listTypes(),
    ])
    setDrones(d.data)
    setTypes(t.data)
    setPayloadTypes(p.data)
  }

  useEffect(() => {
    load()
    fetchVessels()
  }, [])

  const openNew = () => {
    setEditing({ ...BLANK, drone_type_id: types[0]?.id ?? 0 })
    setErr('')
  }

  const save = async () => {
    if (!editing?.call_sign || !editing.serial_number) {
      setErr('Call sign and serial number are required'); return
    }
    setSaving(true); setErr('')
    try {
      const created = await droneMasterApi.createDrone({
        call_sign:         editing.call_sign,
        drone_type_id:     editing.drone_type_id,
        serial_number:     editing.serial_number,
        mavlink_system_id: editing.mavlink_system_id,
        notes:             editing.notes,
      })

      // Assign to vessel if selected
      if (editing.home_vessel_id && created.data?.id) {
        await vesselApi.assignDrone(Number(editing.home_vessel_id), created.data.id)
      }

      await load()
      setEditing(null)
    } catch (e: any) {
      setErr(e.response?.data?.detail ?? 'Save failed')
    } finally { setSaving(false) }
  }

  const typeName   = (id: number) => types.find(t => t.id === id)?.name ?? `Type #${id}`
  const vesselName = (id: number | null) => {
    if (!id) return null
    return vessels.find(v => v.id === id)?.vessel_id ?? `Vessel #${id}`
  }

  function PayloadCompatibilityNote({
    droneType,
    payloadTypes,
  }: {
    droneType?: any
    payloadTypes: PayloadType[]
  }) {
    if (!droneType) return null

    const maxPayload = Number(droneType.max_payload_weight_kg ?? 0)
    const candidates = payloadTypes.filter(p => Number(p.weight_kg ?? 0) <= maxPayload)
    const heavyPayloads = payloadTypes.filter(p => Number(p.weight_kg ?? 0) > maxPayload)

    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm" style={{ color: '#334155' }}>
        <p className="font-semibold text-xs uppercase tracking-wide" style={{ color: '#475569' }}>
          Payload compatibility
        </p>
        <p className="mt-1 text-xs" style={{ color: '#6b7280' }}>
          This drone type supports up to <strong>{maxPayload.toFixed(1)} kg</strong> of payload.
        </p>
        {payloadTypes.length === 0 ? (
          <p className="mt-2 text-xs text-slate-500">Loading payload catalog…</p>
        ) : candidates.length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-2">
            {candidates.slice(0, 4).map(payload => (
              <span key={payload.id ?? payload.name} className="rounded-full bg-white px-2 py-1 text-[11px] border border-slate-200">
                {payload.name} ({payload.weight_kg} kg)
              </span>
            ))}
            {candidates.length > 4 && (
              <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] text-slate-600">
                +{candidates.length - 4} more compatible payloads
              </span>
            )}
          </div>
        ) : (
          <p className="mt-2 text-xs text-amber-700">
            No defined payload types currently fit under this drone's payload capacity.
          </p>
        )}
        {heavyPayloads.length > 0 && (
          <p className="mt-2 text-xs text-amber-700">
            {heavyPayloads.length} payload type{heavyPayloads.length === 1 ? '' : 's'} exceed the max payload weight.
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 max-w-3xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold">Registered Drones</h2>
          <p className="text-xs mt-0.5" style={{ color: '#6b7280' }}>
            Individual drone units with call signs and home base assignment
          </p>
        </div>
        <button onClick={openNew} className="da-btn da-btn-primary">
          <Plus size={14} /> Register Drone
        </button>
      </div>

      <div className="da-card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: '1px solid var(--da-border)', background: 'var(--da-surface)' }}>
              {['Call Sign', 'Type', 'Serial No.', 'MAVLink ID', 'Home Vessel', 'Status', 'Flight Hrs'].map(h => (
                <th key={h} className="px-3 py-2 text-left text-xs font-medium" style={{ color: '#4b5563' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {drones.length === 0 && (
              <tr><td colSpan={7} className="text-center py-8 text-sm" style={{ color: '#374151' }}>
                No drones registered yet
              </td></tr>
            )}
            {drones.map((d: any) => (
              <tr key={d.id} style={{ borderBottom: '1px solid var(--da-border)' }}
                className="hover:bg-white/[0.02]">
                <td className="px-3 py-2 font-semibold">{d.call_sign}</td>
                <td className="px-3 py-2 text-xs" style={{ color: '#6b7280' }}>{typeName(d.drone_type_id)}</td>
                <td className="px-3 py-2 mono text-xs" style={{ color: '#6b7280' }}>{d.serial_number}</td>
                <td className="px-3 py-2 mono text-xs text-center">{d.mavlink_system_id}</td>
                <td className="px-3 py-2">
                  {d.home_vessel_id ? (
                    <span className="flex items-center gap-1 text-xs" style={{ color: '#06b6d4' }}>
                      <Anchor size={11} /> {vesselName(d.home_vessel_id)}
                    </span>
                  ) : (
                    <span className="text-xs" style={{ color: '#374151' }}>fixed (ground)</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <span className="da-badge" style={{
                    background: d.status === 'online' ? 'rgba(34,197,94,0.12)' : 'rgba(107,114,128,0.15)',
                    color: d.status === 'online' ? '#22c55e' : '#6b7280',
                  }}>{d.status}</span>
                </td>
                <td className="px-3 py-2 mono text-xs">{Number(d.total_flight_hours).toFixed(1)} h</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Register drone modal */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(0,0,0,0.75)' }} onClick={() => setEditing(null)}>
          <div className="da-card w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-semibold">Register Drone</h3>
              <button onClick={() => setEditing(null)}><X size={16} style={{ color: '#6b7280' }} /></button>
            </div>
            <div className="flex flex-col gap-3">
              {[
                { k: 'call_sign',         label: 'CALL SIGN *',       type: 'text'   },
                { k: 'serial_number',     label: 'SERIAL NUMBER *',   type: 'text'   },
                { k: 'mavlink_system_id', label: 'MAVLINK SYSTEM ID', type: 'number' },
              ].map(({ k, label, type }) => (
                <label key={k} className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>{label}</span>
                  <input type={type} className="da-input"
                    value={String((editing as any)[k])}
                    onChange={e => setEditing(p => ({
                      ...p!, [k]: type === 'number' ? Number(e.target.value) : e.target.value
                    }))} />
                </label>
              ))}

              <label className="flex flex-col gap-1">
                <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>DRONE TYPE</span>
                <select className="da-input" value={editing.drone_type_id}
                  onChange={e => setEditing(p => ({ ...p!, drone_type_id: Number(e.target.value) }))}>
                  {types.map(t => (
                    <option key={t.id} value={t.id}>
                      {t.name} — max payload {Number(t.max_payload_weight_kg ?? 0).toFixed(1)} kg
                    </option>
                  ))}
                </select>
              </label>

              {editing.drone_type_id && (
                <PayloadCompatibilityNote
                  droneType={types.find(t => t.id === editing.drone_type_id)}
                  payloadTypes={payloadTypes}
                />
              )}

              {/* Vessel assignment */}
              <label className="flex flex-col gap-1">
                <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>HOME BASE</span>
                <select className="da-input" value={editing.home_vessel_id}
                  onChange={e => setEditing(p => ({ ...p!, home_vessel_id: e.target.value ? Number(e.target.value) : '' }))}>
                  <option value="">Fixed ground base</option>
                  {vessels.map(v => (
                    <option key={v.id} value={v.id}>
                      {v.vessel_id} — {v.name} ({v.vessel_type})
                    </option>
                  ))}
                </select>
                {editing.home_vessel_id && (
                  <p className="text-[11px] mt-0.5" style={{ color: '#06b6d4' }}>
                    Drone will use dynamic return-to-ship instead of fixed RTH
                  </p>
                )}
              </label>

              <label className="flex flex-col gap-1">
                <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>NOTES</span>
                <textarea className="da-input text-sm" rows={2}
                  value={editing.notes}
                  onChange={e => setEditing(p => ({ ...p!, notes: e.target.value }))} />
              </label>
            </div>

            {err && <p className="mt-2 text-xs" style={{ color: '#ef4444' }}>{err}</p>}
            <div className="flex gap-2 mt-4">
              <button onClick={() => setEditing(null)} className="da-btn da-btn-ghost flex-1">Cancel</button>
              <button onClick={save} disabled={saving} className="da-btn da-btn-primary flex-1">
                <Save size={14} />{saving ? 'Saving…' : 'Register'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
