import { useEffect, useMemo, useState } from 'react'
import { Edit2, Package, Plus, Save, Trash2, X } from 'lucide-react'
import { payloadApi, type PayloadType } from '@/api/payload'
import { ConfirmModal } from '@/components/common/ConfirmModal'

const STORAGE_KEY = 'da_payload_types_fallback'

const BLANK: PayloadType = {
  name: '',
  manufacturer: '',
  model: '',
  category: 'sensor',
  weight_kg: 0.5,
  voltage_v: 5,
  max_current_a: 2,
  has_gimbal: false,
  notes: '',
}

const CATEGORIES: PayloadType['category'][] = ['sensor', 'combat', 'comms', 'other']
const SENSOR_TYPES = ['EO', 'IR', 'EO/IR', 'SAR', 'LIDAR', 'Hyperspectral', 'SIGINT', 'AIS', 'Other']

function readFallback(): PayloadType[] {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
  } catch {
    return []
  }
}

function writeFallback(payloads: PayloadType[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payloads))
}

export default function PayloadManager() {
  const [payloads, setPayloads] = useState<PayloadType[]>([])
  const [editing, setEditing] = useState<PayloadType | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<PayloadType | null>(null)
  const [isNew, setIsNew] = useState(false)
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [usingFallback, setUsingFallback] = useState(false)

  const totalWeight = useMemo(
    () => payloads.reduce((sum, p) => sum + Number(p.weight_kg || 0), 0),
    [payloads],
  )

  const load = async () => {
    setLoading(true); setErr('')
    try {
      const { data } = await payloadApi.listTypes()
      setPayloads(data)
      setUsingFallback(false)
    } catch (e: any) {
      setPayloads(readFallback())
      setUsingFallback(true)
      setErr(e.response?.data?.detail ?? 'P2-02 payload API is not reachable; using local UI cache.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const openNew = () => {
    setEditing({ ...BLANK })
    setIsNew(true)
    setErr('')
  }

  const openEdit = (payload: PayloadType) => {
    setEditing({ ...payload })
    setIsNew(false)
    setErr('')
  }

  const close = () => {
    setEditing(null)
    setErr('')
  }

  const saveFallback = (payload: PayloadType) => {
    const next = isNew
      ? [{ ...payload, id: Date.now() }, ...payloads]
      : payloads.map(p => p.id === payload.id ? payload : p)
    setPayloads(next)
    writeFallback(next)
  }

  const save = async () => {
    if (!editing?.name.trim()) { setErr('Name is required'); return }
    if (!editing.manufacturer.trim()) { setErr('Manufacturer is required'); return }
    if (!editing.model.trim()) { setErr('Model is required'); return }

    setSaving(true); setErr('')
    try {
      if (usingFallback) {
        saveFallback(editing)
      } else if (isNew) {
        await payloadApi.createType(editing)
        await load()
      } else if (editing.id != null) {
        await payloadApi.updateType(editing.id, editing)
        await load()
      }
      close()
    } catch (e: any) {
      setErr(e.response?.data?.detail ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    if (!deleteTarget?.id) return
    setSaving(true); setErr('')
    try {
      if (usingFallback) {
        const next = payloads.filter(p => p.id !== deleteTarget.id)
        setPayloads(next)
        writeFallback(next)
      } else {
        await payloadApi.deleteType(deleteTarget.id)
        await load()
      }
      setDeleteTarget(null)
    } catch (e: any) {
      setErr(e.response?.data?.detail ?? 'Delete failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-4 max-w-5xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold">Payload Types</h2>
          <p className="text-xs mt-0.5" style={{ color: '#64748b' }}>
            Sensor, combat, comms, and mission equipment catalog for drone assignment.
          </p>
        </div>
        <button onClick={openNew} className="da-btn da-btn-primary">
          <Plus size={14} /> Add Payload
        </button>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {[
          ['Payload Types', payloads.length.toString(), '#2563eb'],
          ['Total Payload Weight', `${totalWeight.toFixed(1)} kg`, '#0f766e'],
          ['Sensors', payloads.filter(p => p.category === 'sensor').length.toString(), '#16a34a'],
        ].map(([label, value, color]) => (
          <div key={label} className="da-card px-4 py-3">
            <div className="text-xl font-bold mono" style={{ color }}>{value}</div>
            <div className="text-xs" style={{ color: '#64748b' }}>{label}</div>
          </div>
        ))}
      </div>

      {usingFallback && (
        <div className="flex items-start gap-3 px-4 py-3 rounded"
          style={{ background: '#eff6ff', border: '1px solid #bfdbfe', color: '#1e40af' }}>
          <Package size={15} style={{ marginTop: 1, flexShrink: 0 }} />
          <p className="text-xs">
            P2-02 payload API was not reachable, so this UI is using a local cache for usability.
            When the endpoint is available, refresh this screen to use backend data.
          </p>
        </div>
      )}

      {err && !usingFallback && (
        <p className="text-xs px-3 py-2 rounded" style={{ background: '#fee2e2', color: '#b91c1c' }}>
          {err}
        </p>
      )}

      <div className="da-card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: '1px solid var(--da-border)', background: '#f8fafc' }}>
              {['Name', 'Manufacturer', 'Model', 'Category', 'Sensor', 'Weight', 'Power', 'Gimbal', 'Actions'].map(h => (
                <th key={h} className="px-3 py-2 text-left text-xs font-medium" style={{ color: '#475569' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={9} className="text-center py-8 text-sm" style={{ color: '#64748b' }}>Loading payloads...</td></tr>
            )}
            {!loading && payloads.length === 0 && (
              <tr><td colSpan={9} className="text-center py-10 text-sm" style={{ color: '#64748b' }}>No payload types defined yet.</td></tr>
            )}
            {!loading && payloads.map(p => (
              <tr key={p.id ?? p.name} style={{ borderBottom: '1px solid var(--da-border)' }} className="hover:bg-slate-50">
                <td className="px-3 py-2 font-medium">{p.name}</td>
                <td className="px-3 py-2 text-xs" style={{ color: '#475569' }}>{p.manufacturer}</td>
                <td className="px-3 py-2 text-xs" style={{ color: '#475569' }}>{p.model}</td>
                <td className="px-3 py-2">
                  <span className="da-badge" style={{
                    background: p.category === 'sensor' ? '#dbeafe' : p.category === 'combat' ? '#fee2e2' : '#ccfbf1',
                    color: p.category === 'sensor' ? '#1d4ed8' : p.category === 'combat' ? '#b91c1c' : '#0f766e',
                  }}>{p.category}</span>
                </td>
                <td className="px-3 py-2 text-xs" style={{ color: '#475569' }}>{p.sensor_type || '-'}</td>
                <td className="px-3 py-2 mono text-xs">{p.weight_kg} kg</td>
                <td className="px-3 py-2 mono text-xs">{p.voltage_v}V / {p.max_current_a}A</td>
                <td className="px-3 py-2 text-xs" style={{ color: p.has_gimbal ? '#16a34a' : '#64748b' }}>
                  {p.has_gimbal ? 'Yes' : 'No'}
                </td>
                <td className="px-3 py-2">
                  <div className="flex gap-1">
                    <button className="da-btn da-btn-ghost px-2 py-1" title="Edit payload" onClick={() => openEdit(p)}>
                      <Edit2 size={12} />
                    </button>
                    <button className="da-btn da-btn-ghost px-2 py-1" title="Delete payload" onClick={() => setDeleteTarget(p)}>
                      <Trash2 size={12} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(15,23,42,0.45)' }} onClick={close}>
          <div className="da-card w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-semibold">{isNew ? 'Add Payload Type' : 'Edit Payload Type'}</h3>
              <button onClick={close}><X size={16} style={{ color: '#64748b' }} /></button>
            </div>

            <div className="grid grid-cols-2 gap-3">
              {([
                ['name', 'Name *', 'text'],
                ['manufacturer', 'Manufacturer *', 'text'],
                ['model', 'Model *', 'text'],
              ] as [keyof PayloadType, string, string][]).map(([k, label, type]) => (
                <label key={k} className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium uppercase" style={{ color: '#64748b' }}>{label}</span>
                  <input type={type} className="da-input"
                    value={String(editing[k] ?? '')}
                    onChange={e => setEditing(p => ({ ...p!, [k]: e.target.value }))} />
                </label>
              ))}

              <label className="flex flex-col gap-1">
                <span className="text-[10px] font-medium uppercase" style={{ color: '#64748b' }}>Category</span>
                <select className="da-input" value={editing.category}
                  onChange={e => setEditing(p => ({ ...p!, category: e.target.value as PayloadType['category'] }))}>
                  {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </label>

              {([
                ['weight_kg', 'Weight (kg)', 'number'],
                ['voltage_v', 'Voltage (V)', 'number'],
                ['max_current_a', 'Max Current (A)', 'number'],
              ] as [keyof PayloadType, string, string][]).map(([k, label, type]) => (
                <label key={k} className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium uppercase" style={{ color: '#64748b' }}>{label}</span>
                  <input type={type} step="0.1" min="0" className="da-input"
                    value={String(editing[k] ?? '')}
                    onChange={e => setEditing(p => ({ ...p!, [k]: Number(e.target.value) }))} />
                </label>
              ))}

              {editing.category === 'sensor' && (
                <>
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] font-medium uppercase" style={{ color: '#64748b' }}>Sensor Type</span>
                    <select className="da-input" value={editing.sensor_type ?? ''}
                      onChange={e => setEditing(p => ({ ...p!, sensor_type: e.target.value }))}>
                      <option value="">Select sensor</option>
                      {SENSOR_TYPES.map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] font-medium uppercase" style={{ color: '#64748b' }}>Resolution</span>
                    <input className="da-input" placeholder="4K, 12MP"
                      value={editing.resolution ?? ''}
                      onChange={e => setEditing(p => ({ ...p!, resolution: e.target.value }))} />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] font-medium uppercase" style={{ color: '#64748b' }}>Frame Rate</span>
                    <input type="number" min="0" className="da-input"
                      value={editing.frame_rate_fps ?? ''}
                      onChange={e => setEditing(p => ({ ...p!, frame_rate_fps: Number(e.target.value) }))} />
                  </label>
                </>
              )}

              {editing.category === 'combat' && (
                <>
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] font-medium uppercase" style={{ color: '#64748b' }}>Function</span>
                    <select className="da-input" value={editing.payload_function ?? ''}
                      onChange={e => setEditing(p => ({ ...p!, payload_function: e.target.value }))}>
                      <option value="">Select function</option>
                      {['weapon', 'jammer', 'dispenser', 'decoy'].map(f => <option key={f} value={f}>{f}</option>)}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] font-medium uppercase" style={{ color: '#64748b' }}>Effective Range (m)</span>
                    <input type="number" min="0" className="da-input"
                      value={editing.effective_range_m ?? ''}
                      onChange={e => setEditing(p => ({ ...p!, effective_range_m: Number(e.target.value) }))} />
                  </label>
                </>
              )}

              <label className="flex items-center gap-2 cursor-pointer pt-5">
                <input type="checkbox" checked={editing.has_gimbal}
                  onChange={e => setEditing(p => ({ ...p!, has_gimbal: e.target.checked }))} />
                <span className="text-sm" style={{ color: '#334155' }}>Gimbal mounted</span>
              </label>
            </div>

            <label className="flex flex-col gap-1 mt-3">
              <span className="text-[10px] font-medium uppercase" style={{ color: '#64748b' }}>Notes</span>
              <textarea className="da-input text-sm" rows={2}
                value={editing.notes ?? ''}
                onChange={e => setEditing(p => ({ ...p!, notes: e.target.value }))} />
            </label>

            {err && (
              <p className="mt-3 text-xs px-3 py-2 rounded" style={{ background: '#fee2e2', color: '#b91c1c' }}>{err}</p>
            )}

            <div className="flex gap-2 mt-5">
              <button onClick={close} className="da-btn da-btn-ghost flex-1">Cancel</button>
              <button onClick={save} disabled={saving} className="da-btn da-btn-primary flex-1">
                <Save size={14} /> {saving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}

      {deleteTarget && (
        <ConfirmModal
          title="Delete Payload Type"
          message={`Delete ${deleteTarget.name}? This removes it from the payload catalog.`}
          confirmLabel="Delete"
          variant="danger"
          isLoading={saving}
          onConfirm={remove}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  )
}
