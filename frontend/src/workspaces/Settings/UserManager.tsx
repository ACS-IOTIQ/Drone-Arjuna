
// ═══════════════════════════════════════════
// UserManager.tsx
// ═══════════════════════════════════════════
import { useEffect, useState } from 'react'
import { Plus, X, Save } from 'lucide-react'
import { api } from '@/api/client'

interface UserRecord {
  id?: number; username: string; email: string
  full_name: string; role: string; is_active: boolean; password?: string
}
const BLANK: UserRecord = {
  username: '', email: '', full_name: '', role: 'viewer', is_active: true, password: ''
}
const ROLES = ['admin', 'mission_commander', 'flight_controller', 'viewer']

export function UserManager() {
  const [users, setUsers]     = useState<UserRecord[]>([])
  const [editing, setEditing] = useState<UserRecord | null>(null)
  const [saving, setSaving]   = useState(false)
  const [err, setErr]         = useState('')

  const load = async () => {
    try { const { data } = await api.get('/api/auth/users'); setUsers(data) }
    catch { /* admin endpoint may not exist yet */ }
  }
  useEffect(() => { load() }, [])

  const save = async () => {
    setSaving(true); setErr('')
    try {
      await api.post('/api/auth/register', editing)
      await load(); setEditing(null)
    } catch (e: any) {
      setErr(e.response?.data?.detail ?? 'Save failed')
    } finally { setSaving(false) }
  }

  return (
    <div className="flex flex-col gap-4 max-w-3xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold">Users</h2>
          <p className="text-xs mt-0.5" style={{ color: '#6b7280' }}>Manage operator accounts and roles</p>
        </div>
        <button onClick={() => setEditing({ ...BLANK })} className="da-btn da-btn-primary">
          <Plus size={14} /> Add User
        </button>
      </div>

      <div className="da-card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: '1px solid var(--da-border)', background: 'var(--da-surface)' }}>
              {['Username','Full Name','Email','Role','Status'].map(h => (
                <th key={h} className="px-3 py-2 text-left text-xs font-medium"
                  style={{ color: '#4b5563' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {users.length === 0 && (
              <tr><td colSpan={5} className="text-center py-8 text-sm" style={{ color: '#374151' }}>
                No users loaded — admin endpoint required
              </td></tr>
            )}
            {users.map((u: any) => (
              <tr key={u.id} style={{ borderBottom: '1px solid var(--da-border)' }}
                className="hover:bg-white/[0.02]">
                <td className="px-3 py-2 font-medium mono">{u.username}</td>
                <td className="px-3 py-2" style={{ color: '#94a3b8' }}>{u.full_name}</td>
                <td className="px-3 py-2 text-xs" style={{ color: '#6b7280' }}>{u.email}</td>
                <td className="px-3 py-2">
                  <span className="da-badge" style={{
                    background: 'rgba(59,130,246,0.12)', color: '#3b82f6',
                  }}>{u.role}</span>
                </td>
                <td className="px-3 py-2">
                  <span className="da-badge" style={{
                    background: u.is_active ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
                    color: u.is_active ? '#22c55e' : '#ef4444',
                  }}>{u.is_active ? 'active' : 'disabled'}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(0,0,0,0.75)' }} onClick={() => setEditing(null)}>
          <div className="da-card w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-semibold">Add User</h3>
              <button onClick={() => setEditing(null)}><X size={16} style={{ color: '#6b7280' }} /></button>
            </div>
            <div className="flex flex-col gap-3">
              {[
                { k: 'username',  l: 'USERNAME *' },
                { k: 'password',  l: 'PASSWORD *', t: 'password' },
                { k: 'email',     l: 'EMAIL *',    t: 'email' },
                { k: 'full_name', l: 'FULL NAME' },
              ].map(({ k, l, t = 'text' }) => (
                <label key={k} className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>{l}</span>
                  <input type={t} className="da-input"
                    value={String((editing as any)[k] ?? '')}
                    onChange={e => setEditing(p => ({ ...p!, [k]: e.target.value }))} />
                </label>
              ))}
              <label className="flex flex-col gap-1">
                <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>ROLE</span>
                <select className="da-input" value={editing.role}
                  onChange={e => setEditing(p => ({ ...p!, role: e.target.value }))}>
                  {ROLES.map(r => <option key={r}>{r}</option>)}
                </select>
              </label>
            </div>
            {err && <p className="mt-2 text-xs" style={{ color: '#ef4444' }}>{err}</p>}
            <div className="flex gap-2 mt-4">
              <button onClick={() => setEditing(null)} className="da-btn da-btn-ghost flex-1">Cancel</button>
              <button onClick={save} disabled={saving} className="da-btn da-btn-primary flex-1">
                <Save size={14} />{saving ? 'Saving…' : 'Create User'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default UserManager