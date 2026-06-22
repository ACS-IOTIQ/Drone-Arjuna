import { useState } from 'react'
import { CheckCircle2, Lock, Mail, Phone, ShieldCheck, User, UserPlus } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import {
  createAccessRequest,
  requestMailto,
  requestSms,
  REQUEST_ROLES,
  type AccessRequest,
} from '@/store/accessRequestStore'
import { notify } from '@/store/notificationStore'

type Mode = 'signin' | 'request'

const EMPTY_REQUEST = {
  username: '',
  full_name: '',
  email: '',
  mobile: '',
  requested_role: 'viewer',
  reason: '',
  admin_note: '',
  temp_password: '',
}

export default function LoginScreen() {
  const { login, isLoading, error } = useAuthStore()
  const [mode, setMode] = useState<Mode>('signin')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [request, setRequest] = useState(EMPTY_REQUEST)
  const [submitted, setSubmitted] = useState<AccessRequest | null>(null)
  const [requestError, setRequestError] = useState('')

  const submitLogin = (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!username.trim() || !password || isLoading) return
    login(username.trim(), password)
  }

  const submitRequest = (e?: React.FormEvent) => {
    e?.preventDefault()
    setRequestError('')
    if (!request.username.trim() || !request.full_name.trim() || !request.email.trim()) {
      setRequestError('Name, username, and email are required.')
      return
    }

    const saved = createAccessRequest({
      ...request,
      username: request.username.trim(),
      full_name: request.full_name.trim(),
      email: request.email.trim(),
      mobile: request.mobile.trim(),
      reason: request.reason.trim(),
    })
    notify.info('Access request submitted', `${saved.full_name} requested ${saved.requested_role} access`)
    setSubmitted(saved)
    setRequest(EMPTY_REQUEST)
  }

  const requestField = (
    key: keyof typeof EMPTY_REQUEST,
    label: string,
    icon: React.ReactNode,
    type = 'text',
    required = false,
  ) => (
    <label className="flex flex-col gap-1.5">
      <span className="text-sm font-semibold leading-tight text-slate-700">
        {label}{required ? ' *' : ''}
      </span>
      <div className="relative">
        <span className="pointer-events-none absolute left-3 top-1/2 flex -translate-y-1/2 items-center text-slate-400">
          {icon}
        </span>
        <input
          type={type}
          className="da-input h-11 pl-9"
          value={request[key]}
          onChange={e => setRequest(prev => ({ ...prev, [key]: e.target.value }))}
        />
      </div>
    </label>
  )

  return (
    <main className="da-login-bg min-h-screen w-full overflow-x-hidden overflow-y-auto px-4 py-6 text-slate-950">
      <div className="pointer-events-none absolute inset-0 da-login-grid" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-1/2 da-login-runway" />

      <div
        className="relative z-10 mx-auto flex min-h-[calc(100vh-3rem)] w-full items-center"
        style={{ maxWidth: 'min(32rem, calc(100vw - 4rem))' }}
      >
        <section className="da-login-card min-w-0 w-full p-5 sm:p-6 max-h-[calc(100vh-3rem)] overflow-y-auto">
          <div className="mb-5 text-center">
            <div
              className="mx-auto mb-4 flex h-[52px] w-[52px] items-center justify-center rounded-xl text-white shadow-lg shadow-blue-950/20"
              style={{ background: 'linear-gradient(135deg, #2563eb, #0f766e)' }}
            >
              <ShieldCheck size={28} />
            </div>
            <h1 className="text-3xl font-bold leading-tight text-slate-950">DroneArjuna</h1>
            <p className="mt-1 text-sm text-slate-600">Ground Control System</p>
          </div>

          <div className="mb-5 grid min-h-11 grid-cols-2 rounded-lg border border-slate-200 bg-slate-100 p-1">
            <button
              type="button"
              onClick={() => setMode('signin')}
              className="min-w-0 whitespace-nowrap rounded-md px-2 py-2 text-[13px] font-semibold leading-none transition-colors sm:text-sm"
              style={{
                background: mode === 'signin' ? '#ffffff' : 'transparent',
                color: mode === 'signin' ? '#1d4ed8' : '#475569',
                boxShadow: mode === 'signin' ? '0 1px 4px rgba(15,23,42,0.08)' : 'none',
              }}
            >
              Sign In
            </button>
            <button
              type="button"
              onClick={() => setMode('request')}
              className="min-w-0 whitespace-nowrap rounded-md px-2 py-2 text-[13px] font-semibold leading-none transition-colors sm:text-sm"
              style={{
                background: mode === 'request' ? '#ffffff' : 'transparent',
                color: mode === 'request' ? '#0f766e' : '#475569',
                boxShadow: mode === 'request' ? '0 1px 4px rgba(15,23,42,0.08)' : 'none',
              }}
            >
              Request Access
            </button>
          </div>

          {mode === 'signin' ? (
            <form onSubmit={submitLogin} className="flex flex-col gap-4">
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-semibold leading-tight text-slate-700">Username</span>
                <div className="relative">
                  <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    className="da-input h-11 pl-9"
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                    autoComplete="username"
                    autoFocus
                  />
                </div>
              </label>

              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-semibold leading-tight text-slate-700">Password</span>
                <div className="relative">
                  <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    type="password"
                    className="da-input h-11 pl-9"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    autoComplete="current-password"
                  />
                </div>
              </label>

              {error && (
                <p className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={isLoading || !username.trim() || !password}
                className="da-btn da-btn-primary h-11 justify-center text-sm font-semibold"
              >
                {isLoading ? 'Signing in...' : 'Sign In'}
              </button>
            </form>
          ) : (
            <form onSubmit={submitRequest} className="flex flex-col gap-3">
              {submitted ? (
                <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
                  <div className="mb-3 flex items-center gap-2 font-semibold">
                    <CheckCircle2 size={16} /> Request queued for admin review.
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <a className="da-btn da-btn-ghost text-xs" href={requestMailto(submitted)}>
                      <Mail size={13} /> Email
                    </a>
                    {submitted.mobile && (
                      <a className="da-btn da-btn-ghost text-xs" href={requestSms(submitted)}>
                        <Phone size={13} /> SMS
                      </a>
                    )}
                    <button type="button" className="da-btn da-btn-primary text-xs" onClick={() => setSubmitted(null)}>
                      New Request
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  {requestField('full_name', 'Full Name', <User size={15} />, 'text', true)}
                  {requestField('username', 'Requested Username', <UserPlus size={15} />, 'text', true)}
                  {requestField('email', 'Email', <Mail size={15} />, 'email', true)}
                  {requestField('mobile', 'Mobile', <Phone size={15} />)}

                  <label className="flex flex-col gap-1.5">
                    <span className="text-sm font-semibold leading-tight text-slate-700">Requested Role *</span>
                    <select
                      className="da-input h-11"
                      value={request.requested_role}
                      onChange={e => setRequest(prev => ({ ...prev, requested_role: e.target.value }))}
                    >
                      {REQUEST_ROLES.map(role => <option key={role} value={role}>{role}</option>)}
                    </select>
                  </label>

                  <label className="flex flex-col gap-1.5">
                    <span className="text-sm font-semibold leading-tight text-slate-700">Reason</span>
                    <textarea
                      className="da-input min-h-20"
                      rows={2}
                      value={request.reason}
                      onChange={e => setRequest(prev => ({ ...prev, reason: e.target.value }))}
                    />
                  </label>

                  {requestError && (
                    <p className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                      {requestError}
                    </p>
                  )}

                  <button type="submit" className="da-btn da-btn-primary h-11 justify-center text-sm font-semibold">
                    Submit Request
                  </button>
                </>
              )}
            </form>
          )}
        </section>
      </div>
    </main>
  )
}
