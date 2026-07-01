import { useEffect, useMemo, useState } from 'react'
import { Mail, Phone, Plus, Save, UserCheck, UserX, X } from 'lucide-react'
import { api } from '@/api/client'
import {
  listAccessRequests,
  makeTempPassword,
  requestMailto,
  requestSms,
  updateAccessRequest,
  type AccessRequest,
} from '@/store/accessRequestStore'
import { notify } from '@/store/notificationStore'

interface AccessRequestOut {
  id: number
  username: string
  full_name: string
  email: string
  mobile?: string
  requested_role: string
  reason?: string
  status: 'pending' | 'approved' | 'rejected'
  admin_note?: string
  temp_password?: string
  created_at: string
  reviewed_at?: string
}

interface UserRecord {
  id?: number
  username: string
  email: string
  full_name: string
  role: string
  is_active: boolean
  password?: string
}

const BLANK: UserRecord = {
  username: '',
  email: '',
  full_name: '',
  role: 'viewer',
  is_active: true,
  password: '',
}

const ROLES = ['admin', 'mission_commander', 'flight_controller', 'viewer']

export function UserManager() {
  const [users, setUsers] = useState<UserRecord[]>([])
  const [requests, setRequests] = useState<AccessRequestOut[]>([])
  const [editing, setEditing] = useState<UserRecord | null>(null)
  const [saving, setSaving] = useState(false)
  const [approvingId, setApprovingId] = useState<number | null>(null)
  const [err, setErr] = useState('')
  const [requestErr, setRequestErr] = useState('')

  const pendingCount = useMemo(
    () => requests.filter(req => req.status === 'pending').length,
    [requests],
  )

  const loadUsers = async () => {
    try {
      const { data } = await api.get('/api/auth/users')
      setUsers(data)
    } catch {
      setUsers([])
    }
  }

  const loadRequests = async () => {
    try {
      const { data } = await api.get('/api/auth/access-requests')
      setRequests(data)
    } catch {
      setRequests([])
    }
  }

  useEffect(() => {
    loadUsers()
    loadRequests()
  }, [])

  const save = async () => {
    if (!editing?.username || !editing.email || !editing.password) {
      setErr('Username, email, and password are required')
      return
    }
    setSaving(true); setErr('')
    try {
      await api.post('/api/auth/register', editing)
      await loadUsers()
      setEditing(null)
    } catch (e: any) {
      setErr(e.response?.data?.detail ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const approveRequest = async (req: AccessRequestOut) => {
    setRequestErr('')
    try {
      setApprovingId(req.id)
      await api.post('/api/auth/register', body)
      await loadUsers()
      updateAccessRequest(req.id, {
        status: 'approved',
        reviewed_at: new Date().toISOString(),
        temp_password: tempPassword,
        admin_note: 'Account created. Send credentials through the approved channel.',
      })
      notify.success('Access approved', `${req.username} account created`)
      loadRequests()
    } catch (e: any) {
      setRequestErr(e.response?.data?.detail ?? 'Approval failed. Confirm you are logged in as admin.')
    } finally {
      setApprovingId(null)
    }
  }

  const rejectRequest = (req: AccessRequest) => {
    updateAccessRequest(req.id, {
      status: 'rejected',
      reviewed_at: new Date().toISOString(),
      admin_note: 'Request rejected by administrator.',
    })
    notify.warning('Access rejected', `${req.username} request rejected`)
    loadRequests()
  }

  return (
    <div className="flex max-w-6xl flex-col gap-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold">Operators & Access</h2>
          <p className="text-xs mt-0.5" style={{ color: '#64748b' }}>
            Manage operator accounts and review account creation requests.
          </p>
        </div>
        <button onClick={() => setEditing({ ...BLANK })} className="da-btn da-btn-primary">
          <Plus size={14} /> Add User
        </button>
      </div>

      <section className="da-card overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--da-border)' }}>
          <div>
            <h3 className="text-sm font-semibold">Access Requests</h3>
            <p className="text-xs" style={{ color: '#64748b' }}>{pendingCount} pending review</p>
          </div>
          {requestErr && <p className="text-xs" style={{ color: '#dc2626' }}>{requestErr}</p>}
        </div>

        {requests.length === 0 ? (
          <p className="px-4 py-6 text-sm" style={{ color: '#64748b' }}>
            No account requests yet. Requests submitted from the login screen appear here.
          </p>
        ) : (
          <div className="divide-y divide-slate-200">
            {requests.map(req => (
              <div key={req.id} className="grid gap-3 p-4 lg:grid-cols-[1.4fr_0.9fr_auto]">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{req.full_name}</span>
                    <span className="mono text-xs" style={{ color: '#64748b' }}>{req.username}</span>
                    <span className="da-badge" style={{
                      background: req.status === 'pending' ? '#fef3c7' : req.status === 'approved' ? '#dcfce7' : '#fee2e2',
                      color: req.status === 'pending' ? '#92400e' : req.status === 'approved' ? '#166534' : '#991b1b',
                    }}>{req.status}</span>
                  </div>
                  <p className="mt-1 text-xs" style={{ color: '#64748b' }}>{req.reason || 'No reason provided.'}</p>
                  {req.temp_password && (
                    <p className="mt-1 text-xs mono" style={{ color: '#0f766e' }}>
                      Temp password: {req.temp_password}
                    </p>
                  )}
                </div>

                <div className="text-xs leading-5" style={{ color: '#475569' }}>
                  <div>{req.email}</div>
                  <div>{req.mobile || 'No mobile number'}</div>
                  <div>Role: {req.requested_role}</div>
                </div>

                <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                  <a className="da-btn da-btn-ghost text-xs" href={requestMailto(req as any)}>
                    <Mail size={13} /> Email
                  </a>
                  {req.mobile && (
                    <a className="da-btn da-btn-ghost text-xs" href={requestSms(req as any)}>
                      <Phone size={13} /> SMS
                    </a>
                  )}
                  {req.status === 'pending' && (
                    <>
                      <button
                        className="da-btn da-btn-success text-xs"
                        disabled={approvingId === req.id}
                        onClick={() => approveRequest(req)}
                      >
                        <UserCheck size={13} /> {approvingId === req.id ? 'Creating...' : 'Allow'}
                      </button>
                      <button className="da-btn da-btn-danger text-xs" onClick={() => rejectRequest(req)}>
                        <UserX size={13} /> Reject
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="da-card overflow-hidden">
        <div className="px-4 py-3" style={{ borderBottom: '1px solid var(--da-border)' }}>
          <h3 className="text-sm font-semibold">Operator Accounts</h3>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: '1px solid var(--da-border)', background: '#f8fafc' }}>
              {['Username', 'Full Name', 'Email', 'Role', 'Status'].map(h => (
                <th key={h} className="px-3 py-2 text-left text-xs font-medium" style={{ color: '#475569' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {users.length === 0 && (
              <tr><td colSpan={5} className="text-center py-8 text-sm" style={{ color: '#64748b' }}>
                No users loaded. Admin endpoint requires an admin login.
              </td></tr>
            )}
            {users.map((user: any) => (
              <tr key={user.id ?? user.username} style={{ borderBottom: '1px solid var(--da-border)' }} className="hover:bg-slate-50">
                <td className="px-3 py-2 font-medium mono">{user.username}</td>
                <td className="px-3 py-2" style={{ color: '#334155' }}>{user.full_name}</td>
                <td className="px-3 py-2 text-xs" style={{ color: '#64748b' }}>{user.email}</td>
                <td className="px-3 py-2">
                  <span className="da-badge" style={{ background: '#dbeafe', color: '#1d4ed8' }}>{user.role}</span>
                </td>
                <td className="px-3 py-2">
                  <span className="da-badge" style={{
                    background: user.is_active ? '#dcfce7' : '#fee2e2',
                    color: user.is_active ? '#166534' : '#991b1b',
                  }}>{user.is_active ? 'active' : 'disabled'}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(15,23,42,0.45)' }} onClick={() => setEditing(null)}>
          <div className="da-card w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-semibold">Add User</h3>
              <button onClick={() => setEditing(null)}><X size={16} style={{ color: '#64748b' }} /></button>
            </div>
            <div className="flex flex-col gap-3">
              {[
                { k: 'username', l: 'USERNAME *' },
                { k: 'password', l: 'PASSWORD *', t: 'password' },
                { k: 'email', l: 'EMAIL *', t: 'email' },
                { k: 'full_name', l: 'FULL NAME' },
              ].map(({ k, l, t = 'text' }) => (
                <label key={k} className="flex flex-col gap-1">
                  <span className="text-[10px] font-medium" style={{ color: '#64748b' }}>{l}</span>
                  <input type={t} className="da-input"
                    value={String((editing as any)[k] ?? '')}
                    onChange={e => setEditing(prev => ({ ...prev!, [k]: e.target.value }))} />
                </label>
              ))}
              <label className="flex flex-col gap-1">
                <span className="text-[10px] font-medium" style={{ color: '#64748b' }}>ROLE</span>
                <select className="da-input" value={editing.role}
                  onChange={e => setEditing(prev => ({ ...prev!, role: e.target.value }))}>
                  {ROLES.map(role => <option key={role} value={role}>{role}</option>)}
                </select>
              </label>
            </div>
            {err && <p className="mt-2 text-xs" style={{ color: '#dc2626' }}>{err}</p>}
            <div className="flex gap-2 mt-4">
              <button onClick={() => setEditing(null)} className="da-btn da-btn-ghost flex-1">
                <X size={14} /> Cancel
              </button>
              <button onClick={save} disabled={saving} className="da-btn da-btn-primary flex-1">
                <Save size={14} />{saving ? 'Saving...' : 'Create User'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default UserManager
