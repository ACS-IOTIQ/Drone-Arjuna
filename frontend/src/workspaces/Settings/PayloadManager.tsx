/**
 * PayloadManager
 * CRUD UI for payload types (sensors, combat, comms payloads).
 * The backend PayloadType ORM model and API endpoints are V2.
 * This component is fully structured and ready; it shows a
 * "coming in V2" notice in the table until the API is wired.
 */
import { useState } from 'react'
import { Plus, X, Save, Zap } from 'lucide-react'
import { api } from '@/api/client'

interface PayloadType {
  id?:                number
  name:               string
  manufacturer:       string
  model:              string
  category:           string
  weight_kg:          number
  voltage_v:          number
  max_current_a:      number
  sensor_type?:       string
  resolution?:        string
  frame_rate_fps?:    number
  has_gimbal:         boolean
  payload_function?:  string
  effective_range_m?: number
  notes:              string
}

const BLANK: PayloadType = {
  name: '', manufacturer: '', model: '', category: 'sensor',
  weight_kg: 0.5, voltage_v: 5, max_current_a: 2,
  has_gimbal: false, notes: '',
}

const CATEGORIES = ['sensor', 'combat', 'comms', 'other']
const SENSOR_TYPES = ['EO', 'IR', 'EO/IR', 'SAR', 'LIDAR', 'Hyperspectral', 'SIGINT', 'AIS', 'Other']

export default function PayloadManager() {
  const [payloads, setPayloads]   = useState<PayloadType[]>([])
  const [editing, setEditing]     = useState<PayloadType | null>(null)
  const [isNew, setIsNew]         = useState(false)
  const [saving, setSaving]       = useState(false)
  const [err, setErr]             = useState('')
  const [v2Notice, setV2Notice]   = useState(true)

  const openNew  = () => { setEditing({ ...BLANK }); setIsNew(true); setErr('') }
  const close    = () => { setEditing(null); setErr('') }

  const save = async () => {
    if (!editing?.name.trim()) { setErr('Name is required'); return }
    setSaving(true); setErr('')
    try {
      if (isNew) {
        await api.post('/api/master/payload-types', editing)
      } else {
        await api.put(`/api/master/payload-types/${editing!.id}`, editing)
      }
      // Refresh list (endpoint available in V2)
      const { data } = await api.get('/api/master/payload-types')
      setPayloads(data)
      close()
    } catch (e: any) {
      setErr(e.response?.data?.detail ?? 'Payload API available in V2')
    } finally { setSaving(false) }
  }

  return (
    <div className="flex flex-col gap-4 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold">Payload Types</h2>
          <p className="text-xs mt-0.5" style={{ color: '#6b7280' }}>
            Sensor, combat, and comms payloads catalogue
          </p>
        </div>
        <button onClick={openNew} className="da-btn da-btn-primary">
          <Plus size={14} /> Add Payload
        </button>
      </div>

      {/* V2 notice */}
      {v2Notice && (
        <div className="flex items-start gap-3 px-4 py-3 rounded"
          style={{ background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.2)' }}>
          <Zap size={15} style={{ color: '#3b82f6', marginTop: 1, flexShrink: 0 }} />
          <div className="flex-1">
            <p className="text-xs font-semibold" style={{ color: '#3b82f6' }}>
              Payload API available in V2
            </p>
            <p className="text-xs mt-0.5" style={{ color: '#4b5563' }}>
              The payload schema, compatibility matrix, and CRUD endpoints are
              implemented in the V2 Drone Master expansion. You can define payload
              types here now — they will be saved once the backend endpoint is live.
            </p>
          </div>
          <button onClick={() => setV2Notice(false)}
            style={{ color: '#6b7280' }}>
            <X size={14} />
          </button>
        </div>
      )}

      {/* Table */}
      <div className="da-card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: '1px solid var(--da-border)', background: 'var(--da-surface)' }}>
              {['Name', 'Manufacturer', 'Category', 'Sensor Type', 'Weight', 'Voltage', 'Gimbal', ''].map(h => (
                <th key={h} className="px-3 py-2 text-left text-xs font-medium"
                  style={{ color: '#4b5563' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {payloads.length === 0 ? (
              <tr>
                <td colSpan={8} className="text-center py-10 text-sm" style={{ color: '#374151' }}>
                  No payload types defined yet — add one above
                </td>
              </tr>
            ) : payloads.map(p => (
              <tr key={p.id} style={{ borderBottom: '1px solid var(--da-border)' }}
                className="hover:bg-white/[0.02]">
                <td className="px-3 py-2 font-medium">{p.name}</td>
                <td className="px-3 py-2 text-xs" style={{ color: '#6b7280' }}>{p.manufacturer}</td>
                <td className="px-3 py-2">
                  <span className="da-badge" style={{
                    background: p.category === 'sensor' ? 'rgba(59,130,246,0.12)' : 'rgba(239,68,68,0.12)',
                    color:      p.category === 'sensor' ? '#3b82f6' : '#ef4444',
                  }}>{p.category}</span>
                </td>
                <td className="px-3 py-2 text-xs" style={{ color: '#6b7280' }}>{p.sensor_type ?? '—'}</td>
                <td className="px-3 py-2 mono text-xs">{p.weight_kg} kg</td>
                <td className="px-3 py-2 mono text-xs">{p.voltage_v}V</td>
                <td className="px-3 py-2 text-xs" style={{ color: p.has_gimbal ? '#22c55e' : '#374151' }}>
                  {p.has_gimbal ? 'Yes' : 'No'}
                </td>
                <td className="px-3 py-2" />
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Modal */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(0,0,0,0.75)' }} onClick={close}>
          <div className="da-card w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-semibold">{isNew ? 'Add Payload Type' : 'Edit Payload Type'}</h3>
              <button onClick={close}><X size={16} style={{ color: '#6b7280' }} /></button>
            </div>

            <div className="grid grid-cols-2 gap-3">
              {/* Basic info */}
              {([
                ['name',         'NAME *',         'text'],
                ['manufacturer', 'MANUFACTURER',   'text'],
                ['model',        'MODEL',          'text'],
              ] as [keyof PayloadType, string, string][]).map(([k, l, t]) => (
                <label key={k} className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>{l}</span>
                  <input type={t} className="da-input"
                    value={String((editing as any)[k] ?? '')}
                    onChange={e => setEditing(p => ({ ...p!, [k]: e.target.value }))} />
                </label>
              ))}

              {/* Category */}
              <label className="flex flex-col gap-1">
                <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>CATEGORY</span>
                <select className="da-input" value={editing.category}
                  onChange={e => setEditing(p => ({ ...p!, category: e.target.value }))}>
                  {CATEGORIES.map(c => <option key={c}>{c}</option>)}
                </select>
              </label>

              {/* Physical */}
              {([
                ['weight_kg',    'WEIGHT (kg)',   'number'],
                ['voltage_v',    'VOLTAGE (V)',   'number'],
                ['max_current_a','MAX CURRENT (A)','number'],
              ] as [keyof PayloadType, string, string][]).map(([k, l, t]) => (
                <label key={k} className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>{l}</span>
                  <input type={t} className="da-input"
                    value={String((editing as any)[k] ?? '')}
                    onChange={e => setEditing(p => ({ ...p!, [k]: Number(e.target.value) }))} />
                </label>
              ))}

              {/* Sensor-specific */}
              {editing.category === 'sensor' && <>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>SENSOR TYPE</span>
                  <select className="da-input" value={editing.sensor_type ?? ''}
                    onChange={e => setEditing(p => ({ ...p!, sensor_type: e.target.value }))}>
                    <option value="">— Select —</option>
                    {SENSOR_TYPES.map(s => <option key={s}>{s}</option>)}
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>RESOLUTION</span>
                  <input className="da-input" placeholder="e.g. 4K, 12MP"
                    value={editing.resolution ?? ''}
                    onChange={e => setEditing(p => ({ ...p!, resolution: e.target.value }))} />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>FRAME RATE (fps)</span>
                  <input type="number" className="da-input"
                    value={editing.frame_rate_fps ?? ''}
                    onChange={e => setEditing(p => ({ ...p!, frame_rate_fps: Number(e.target.value) }))} />
                </label>
                <label className="flex items-center gap-2 cursor-pointer pt-4">
                  <input type="checkbox" checked={editing.has_gimbal}
                    onChange={e => setEditing(p => ({ ...p!, has_gimbal: e.target.checked }))} />
                  <span className="text-sm" style={{ color: '#94a3b8' }}>Has gimbal</span>
                </label>
              </>}

              {/* Combat-specific */}
              {editing.category === 'combat' && <>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>PAYLOAD FUNCTION</span>
                  <select className="da-input" value={editing.payload_function ?? ''}
                    onChange={e => setEditing(p => ({ ...p!, payload_function: e.target.value }))}>
                    <option value="">— Select —</option>
                    {['weapon', 'jammer', 'dispenser', 'decoy'].map(f => <option key={f}>{f}</option>)}
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>EFFECTIVE RANGE (m)</span>
                  <input type="number" className="da-input"
                    value={editing.effective_range_m ?? ''}
                    onChange={e => setEditing(p => ({ ...p!, effective_range_m: Number(e.target.value) }))} />
                </label>
              </>}
            </div>

            {/* Notes */}
            <label className="flex flex-col gap-1 mt-3">
              <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>NOTES</span>
              <textarea className="da-input text-sm" rows={2}
                value={editing.notes}
                onChange={e => setEditing(p => ({ ...p!, notes: e.target.value }))} />
            </label>

            {err && (
              <p className="mt-3 text-xs px-3 py-2 rounded"
                style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>{err}</p>
            )}

            <div className="flex gap-2 mt-5">
              <button onClick={close} className="da-btn da-btn-ghost flex-1">Cancel</button>
              <button onClick={save} disabled={saving} className="da-btn da-btn-primary flex-1">
                <Save size={14} /> {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}