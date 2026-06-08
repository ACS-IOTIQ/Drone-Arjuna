import { useEffect, useState } from 'react'
import { Plus, Pencil, Trash2, X, Save } from 'lucide-react'
import { droneMasterApi } from '@/api/droneMaster'

interface DroneType {
  id?: number
  name: string; manufacturer: string; model: string
  size_class: string; mission_type: string; is_vtol: boolean
  max_speed_ms: number; cruise_speed_ms: number; max_altitude_m: number
  endurance_h: number; range_km: number
  max_takeoff_weight_kg: number; max_payload_weight_kg: number
  autopilot_type: string; notes: string
}

const BLANK: DroneType = {
  name: '', manufacturer: '', model: '', size_class: 'medium',
  mission_type: 'ISR', is_vtol: true,
  max_speed_ms: 30, cruise_speed_ms: 15, max_altitude_m: 3000,
  endurance_h: 2, range_km: 50,
  max_takeoff_weight_kg: 5, max_payload_weight_kg: 1,
  autopilot_type: 'ArduPilot', notes: '',
}

export default function DroneTypeManager() {
  const [types, setTypes]       = useState<DroneType[]>([])
  const [editing, setEditing]   = useState<DroneType | null>(null)
  const [isNew, setIsNew]       = useState(false)
  const [saving, setSaving]     = useState(false)
  const [err, setErr]           = useState('')

  const load = async () => {
    const { data } = await droneMasterApi.listTypes()
    setTypes(data)
  }
  useEffect(() => { load() }, [])

  const openNew  = () => { setEditing({ ...BLANK }); setIsNew(true); setErr('') }
  const openEdit = (t: DroneType) => { setEditing({ ...t }); setIsNew(false); setErr('') }
  const close    = () => { setEditing(null); setErr('') }

  const save = async () => {
    if (!editing || !editing.name.trim()) { setErr('Name is required'); return }
    setSaving(true); setErr('')
    try {
      if (isNew) {
        await droneMasterApi.createType(editing)
      } else {
        await droneMasterApi.updateType(editing.id!, editing)
      }
      await load(); close()
    } catch (e: any) {
      setErr(e.response?.data?.detail ?? 'Save failed')
    } finally { setSaving(false) }
  }

  const archive = async (id: number) => {
    if (!confirm('Archive this drone type?')) return
    await droneMasterApi.archiveType(id)
    await load()
  }

  const field = (k: keyof DroneType, label: string, type = 'text', opts?: string[]) => (
    <label key={k} className="flex flex-col gap-1">
      <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>{label}</span>
      {opts ? (
        <select className="da-input text-sm" value={String(editing![k])}
          onChange={e => setEditing(p => ({ ...p!, [k]: e.target.value }))}>
          {opts.map(o => <option key={o}>{o}</option>)}
        </select>
      ) : type === 'checkbox' ? (
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={Boolean(editing![k])}
            onChange={e => setEditing(p => ({ ...p!, [k]: e.target.checked }))} />
          <span className="text-sm" style={{ color: '#94a3b8' }}>
            {editing![k] ? 'Yes' : 'No'}
          </span>
        </label>
      ) : (
        <input type={type} className="da-input text-sm"
          value={String(editing![k])}
          onChange={e => setEditing(p => ({
            ...p!, [k]: type === 'number' ? Number(e.target.value) : e.target.value
          }))} />
      )}
    </label>
  )

  return (
    <div className="flex flex-col gap-4 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold">Drone Types</h2>
          <p className="text-xs mt-0.5" style={{ color: '#6b7280' }}>
            Define drone platforms and their specifications
          </p>
        </div>
        <button onClick={openNew} className="da-btn da-btn-primary">
          <Plus size={14} /> Add Type
        </button>
      </div>

      {/* Table */}
      <div className="da-card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: '1px solid var(--da-border)', background: 'var(--da-surface)' }}>
              {['Name','Manufacturer','Class','Type','Speed','Altitude','Endurance','Autopilot',''].map(h => (
                <th key={h} className="px-3 py-2 text-left text-xs font-medium"
                  style={{ color: '#4b5563' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {types.length === 0 && (
              <tr><td colSpan={9} className="text-center py-8 text-sm" style={{ color: '#374151' }}>
                No drone types defined yet
              </td></tr>
            )}
            {types.map(t => (
              <tr key={t.id}
                style={{ borderBottom: '1px solid var(--da-border)' }}
                className="hover:bg-white/[0.02] transition-colors">
                <td className="px-3 py-2 font-medium">{t.name}</td>
                <td className="px-3 py-2" style={{ color: '#6b7280' }}>{t.manufacturer}</td>
                <td className="px-3 py-2">
                  <span className="da-badge" style={{ background: 'rgba(59,130,246,0.12)', color: '#3b82f6' }}>
                    {t.size_class}
                  </span>
                </td>
                <td className="px-3 py-2" style={{ color: '#6b7280' }}>{t.mission_type}</td>
                <td className="px-3 py-2 mono text-xs">{t.max_speed_ms} m/s</td>
                <td className="px-3 py-2 mono text-xs">{t.max_altitude_m} m</td>
                <td className="px-3 py-2 mono text-xs">{t.endurance_h} h</td>
                <td className="px-3 py-2" style={{ color: '#6b7280' }}>{t.autopilot_type}</td>
                <td className="px-3 py-2">
                  <div className="flex gap-1">
                    <button onClick={() => openEdit(t)}
                      className="p-1.5 rounded transition-colors hover:bg-white/10"
                      style={{ color: '#3b82f6' }}>
                      <Pencil size={13} />
                    </button>
                    <button onClick={() => archive(t.id!)}
                      className="p-1.5 rounded transition-colors hover:bg-white/10"
                      style={{ color: '#ef4444' }}>
                      <Trash2 size={13} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Edit / Create modal */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(0,0,0,0.75)' }} onClick={close}>
          <div className="da-card w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-semibold">{isNew ? 'Add Drone Type' : 'Edit Drone Type'}</h3>
              <button onClick={close}><X size={16} style={{ color: '#6b7280' }} /></button>
            </div>

            <div className="grid grid-cols-2 gap-3">
              {field('name',                 'NAME *')}
              {field('manufacturer',         'MANUFACTURER')}
              {field('model',                'MODEL')}
              {field('size_class',           'SIZE CLASS',    'text', ['micro','small','medium','large','extra-large'])}
              {field('mission_type',         'MISSION TYPE',  'text', ['ISR','Strike','Patrol','Logistics','SAR','Training','Multi-role'])}
              {field('autopilot_type',       'AUTOPILOT',     'text', ['ArduPilot','PX4','DJI','Custom'])}
              {field('is_vtol',              'VTOL / HOVER',  'checkbox')}
              {field('max_speed_ms',         'MAX SPEED (m/s)',      'number')}
              {field('cruise_speed_ms',      'CRUISE SPEED (m/s)',   'number')}
              {field('max_altitude_m',       'MAX ALTITUDE (m)',     'number')}
              {field('endurance_h',          'ENDURANCE (hours)',    'number')}
              {field('range_km',             'RANGE (km)',           'number')}
              {field('max_takeoff_weight_kg','MAX TAKEOFF WT (kg)',  'number')}
              {field('max_payload_weight_kg','MAX PAYLOAD WT (kg)',  'number')}
            </div>

            <div className="mt-3">
              <label className="flex flex-col gap-1">
                <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>NOTES</span>
                <textarea className="da-input text-sm" rows={2}
                  value={editing.notes}
                  onChange={e => setEditing(p => ({ ...p!, notes: e.target.value }))} />
              </label>
            </div>

            {err && (
              <p className="mt-3 text-xs px-3 py-2 rounded"
                style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>{err}</p>
            )}

            <div className="flex gap-2 mt-5">
              <button onClick={close} className="da-btn da-btn-ghost flex-1">Cancel</button>
              <button onClick={save} disabled={saving}
                className="da-btn da-btn-primary flex-1">
                <Save size={14} /> {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}