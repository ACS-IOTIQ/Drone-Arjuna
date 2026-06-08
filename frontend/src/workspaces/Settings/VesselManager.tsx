import { useEffect, useState } from 'react'
import { Plus, X, Save, Anchor, MapPin } from 'lucide-react'
import { useVesselStore } from '@/store/vesselStore'
import { vesselApi } from '@/api/vessel'
import type { NavalVessel } from '@/store/vesselStore'

interface VesselForm {
  vessel_id: string
  name: string
  vessel_type: string
  hull_number: string
  sea_state: number
  deck_status: string
  landing_spots: number
  hf_modem_type: string
  hf_frequency_mhz: string
  hf_link_encrypted: boolean
  notes: string
}

const BLANK: VesselForm = {
  vessel_id: '', name: '', vessel_type: 'OPV',
  hull_number: '', sea_state: 0, deck_status: 'clear',
  landing_spots: 1, hf_modem_type: 'generic',
  hf_frequency_mhz: '', hf_link_encrypted: true, notes: '',
}

const VESSEL_TYPES = ['Aircraft Carrier', 'Destroyer', 'Frigate', 'Corvette', 'OPV', 'Patrol', 'LST', 'Other']
const MODEM_TYPES  = ['generic', 'harris', 'codan', 'barrett']
const DECK_STATUSES = ['clear', 'occupied', 'restricted']

export default function VesselManager() {
  const { vessels, fetchVessels } = useVesselStore()
  const [editing, setEditing] = useState<VesselForm | null>(null)
  const [saving, setSaving]   = useState(false)
  const [err, setErr]         = useState('')
  const [posEdit, setPosEdit] = useState<{ id: number; lat: string; lon: string; hdg: string; spd: string } | null>(null)
  const [posErr, setPosErr]   = useState('')

  useEffect(() => { fetchVessels() }, [])

  const openNew = () => { setEditing({ ...BLANK }); setErr('') }

  const save = async () => {
    if (!editing!.vessel_id || !editing!.name) {
      setErr('Vessel ID and name are required'); return
    }
    setSaving(true); setErr('')
    try {
      await vesselApi.create({
        ...editing!,
        hf_frequency_mhz: editing!.hf_frequency_mhz ? Number(editing!.hf_frequency_mhz) : undefined,
      })
      await fetchVessels()
      setEditing(null)
    } catch (e: any) {
      setErr(e.response?.data?.detail ?? 'Save failed')
    } finally { setSaving(false) }
  }

  const savePosition = async () => {
    if (!posEdit) return
    const lat = parseFloat(posEdit.lat)
    const lon = parseFloat(posEdit.lon)
    if (isNaN(lat) || isNaN(lon)) { setPosErr('Valid lat/lon required'); return }
    setPosErr('')
    try {
      await vesselApi.updatePosition(posEdit.id, {
        latitude: lat,
        longitude: lon,
        heading_deg: posEdit.hdg ? parseFloat(posEdit.hdg) : undefined,
        speed_kts: posEdit.spd ? parseFloat(posEdit.spd) : undefined,
      })
      await fetchVessels()
      setPosEdit(null)
    } catch (e: any) {
      setPosErr(e.response?.data?.detail ?? 'Update failed')
    }
  }

  const deckColor = (s: string) =>
    s === 'clear' ? { bg: 'rgba(34,197,94,0.12)', fg: '#22c55e' }
    : s === 'occupied' ? { bg: 'rgba(239,68,68,0.12)', fg: '#ef4444' }
    : { bg: 'rgba(245,158,11,0.12)', fg: '#f59e0b' }

  return (
    <div className="flex flex-col gap-4 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold">Naval Vessels</h2>
          <p className="text-xs mt-0.5" style={{ color: '#6b7280' }}>
            Floating home bases for HF-linked ship-borne drone operations
          </p>
        </div>
        <button onClick={openNew} className="da-btn da-btn-primary">
          <Plus size={14} /> Register Vessel
        </button>
      </div>

      {/* Vessel table */}
      <div className="da-card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: '1px solid var(--da-border)', background: 'var(--da-surface)' }}>
              {['Vessel ID', 'Name', 'Type', 'Deck', 'Position', 'HF Modem', 'Spots', ''].map(h => (
                <th key={h} className="px-3 py-2 text-left text-xs font-medium" style={{ color: '#4b5563' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {vessels.length === 0 && (
              <tr><td colSpan={8} className="text-center py-8 text-sm" style={{ color: '#374151' }}>
                No vessels registered
              </td></tr>
            )}
            {vessels.map((v: NavalVessel) => {
              const dc = deckColor(v.deck_status)
              return (
                <tr key={v.id} style={{ borderBottom: '1px solid var(--da-border)' }}
                  className="hover:bg-white/[0.02]">
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1.5">
                      <Anchor size={12} style={{ color: '#06b6d4' }} />
                      <span className="font-semibold mono">{v.vessel_id}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-xs">{v.name}</td>
                  <td className="px-3 py-2 text-xs" style={{ color: '#6b7280' }}>{v.vessel_type}</td>
                  <td className="px-3 py-2">
                    <span className="da-badge text-[11px]" style={{ background: dc.bg, color: dc.fg }}>
                      {v.deck_status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs mono">
                    {v.latitude != null
                      ? <span style={{ color: '#22c55e' }}>{v.latitude.toFixed(4)}, {v.longitude!.toFixed(4)}</span>
                      : <span style={{ color: '#f59e0b' }}>no position</span>
                    }
                  </td>
                  <td className="px-3 py-2 text-xs" style={{ color: '#6b7280' }}>{v.hf_modem_type ?? '—'}</td>
                  <td className="px-3 py-2 text-xs text-center">{v.landing_spots}</td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() => setPosEdit({ id: v.id, lat: String(v.latitude ?? ''), lon: String(v.longitude ?? ''), hdg: String(v.heading_deg ?? ''), spd: String(v.speed_kts ?? '') })}
                      className="da-btn da-btn-ghost py-1 px-2 text-xs flex items-center gap-1">
                      <MapPin size={11} /> Update Pos
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Register vessel modal */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(0,0,0,0.75)' }} onClick={() => setEditing(null)}>
          <div className="da-card w-full max-w-lg p-6 overflow-y-auto max-h-[90vh]"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-semibold flex items-center gap-2">
                <Anchor size={16} style={{ color: '#06b6d4' }} /> Register Naval Vessel
              </h3>
              <button onClick={() => setEditing(null)}><X size={16} style={{ color: '#6b7280' }} /></button>
            </div>

            <div className="flex flex-col gap-3">
              {/* Vessel ID + Name */}
              <div className="grid grid-cols-2 gap-3">
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>VESSEL ID *</span>
                  <input className="da-input mono uppercase" placeholder="INS-VIKRANT"
                    value={editing.vessel_id}
                    onChange={e => setEditing(p => ({ ...p!, vessel_id: e.target.value.toUpperCase() }))} />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>HULL NUMBER</span>
                  <input className="da-input mono" placeholder="R11"
                    value={editing.hull_number}
                    onChange={e => setEditing(p => ({ ...p!, hull_number: e.target.value }))} />
                </label>
              </div>

              <label className="flex flex-col gap-1">
                <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>VESSEL NAME *</span>
                <input className="da-input" placeholder="INS Vikrant"
                  value={editing.name}
                  onChange={e => setEditing(p => ({ ...p!, name: e.target.value }))} />
              </label>

              <div className="grid grid-cols-2 gap-3">
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>VESSEL TYPE</span>
                  <select className="da-input" value={editing.vessel_type}
                    onChange={e => setEditing(p => ({ ...p!, vessel_type: e.target.value }))}>
                    {VESSEL_TYPES.map(t => <option key={t}>{t}</option>)}
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>DECK STATUS</span>
                  <select className="da-input" value={editing.deck_status}
                    onChange={e => setEditing(p => ({ ...p!, deck_status: e.target.value }))}>
                    {DECK_STATUSES.map(s => <option key={s}>{s}</option>)}
                  </select>
                </label>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>LANDING SPOTS</span>
                  <input type="number" min={1} className="da-input"
                    value={editing.landing_spots}
                    onChange={e => setEditing(p => ({ ...p!, landing_spots: Number(e.target.value) }))} />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>SEA STATE (0-9)</span>
                  <input type="number" min={0} max={9} className="da-input"
                    value={editing.sea_state}
                    onChange={e => setEditing(p => ({ ...p!, sea_state: Number(e.target.value) }))} />
                </label>
              </div>

              {/* HF section */}
              <div className="flex flex-col gap-3 p-3 rounded mt-1"
                style={{ background: 'rgba(6,182,212,0.06)', border: '1px solid rgba(6,182,212,0.18)' }}>
                <p className="text-xs font-medium" style={{ color: '#06b6d4' }}>HF Link Configuration</p>
                <div className="grid grid-cols-2 gap-3">
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>MODEM TYPE</span>
                    <select className="da-input" value={editing.hf_modem_type}
                      onChange={e => setEditing(p => ({ ...p!, hf_modem_type: e.target.value }))}>
                      {MODEM_TYPES.map(m => <option key={m}>{m}</option>)}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>FREQUENCY (MHz)</span>
                    <input type="number" className="da-input mono" placeholder="8.0"
                      value={editing.hf_frequency_mhz}
                      onChange={e => setEditing(p => ({ ...p!, hf_frequency_mhz: e.target.value }))} />
                  </label>
                </div>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={editing.hf_link_encrypted}
                    onChange={e => setEditing(p => ({ ...p!, hf_link_encrypted: e.target.checked }))} />
                  <span className="text-xs" style={{ color: '#94a3b8' }}>COMSEC encrypted link (Type 1 modem)</span>
                </label>
              </div>

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
                <Save size={14} />{saving ? 'Saving…' : 'Register Vessel'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Update position modal */}
      {posEdit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(0,0,0,0.75)' }} onClick={() => setPosEdit(null)}>
          <div className="da-card w-full max-w-sm p-6" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold text-sm flex items-center gap-2">
                <MapPin size={15} style={{ color: '#06b6d4' }} /> Update Vessel Position
              </h3>
              <button onClick={() => setPosEdit(null)}><X size={16} style={{ color: '#6b7280' }} /></button>
            </div>
            <div className="flex flex-col gap-3">
              <div className="grid grid-cols-2 gap-3">
                <label className="flex flex-col gap-1">
                  <span className="text-[10px]" style={{ color: '#94a3b8' }}>LATITUDE</span>
                  <input className="da-input mono" placeholder="12.345678"
                    value={posEdit.lat}
                    onChange={e => setPosEdit(p => ({ ...p!, lat: e.target.value }))} />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px]" style={{ color: '#94a3b8' }}>LONGITUDE</span>
                  <input className="da-input mono" placeholder="77.123456"
                    value={posEdit.lon}
                    onChange={e => setPosEdit(p => ({ ...p!, lon: e.target.value }))} />
                </label>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="flex flex-col gap-1">
                  <span className="text-[10px]" style={{ color: '#94a3b8' }}>HEADING (°)</span>
                  <input className="da-input mono" placeholder="045"
                    value={posEdit.hdg}
                    onChange={e => setPosEdit(p => ({ ...p!, hdg: e.target.value }))} />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px]" style={{ color: '#94a3b8' }}>SPEED (kts)</span>
                  <input className="da-input mono" placeholder="12.5"
                    value={posEdit.spd}
                    onChange={e => setPosEdit(p => ({ ...p!, spd: e.target.value }))} />
                </label>
              </div>
              {posErr && <p className="text-xs" style={{ color: '#ef4444' }}>{posErr}</p>}
              <div className="flex gap-2 mt-1">
                <button onClick={() => setPosEdit(null)} className="da-btn da-btn-ghost flex-1">Cancel</button>
                <button onClick={savePosition} className="da-btn da-btn-primary flex-1">
                  <MapPin size={13} /> Update
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
