import { useEffect, useState } from 'react'
import {
  ArrowRight, CheckCircle2, Eye, EyeOff, KeyRound, Lock, Mail, Phone,
  Radio, ShieldCheck, User, UserPlus,
} from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import { REQUEST_ROLES, requestMailto, requestSms, type AccessRequest } from '@/store/accessRequestStore'
import { api } from '@/api/client'
import { notify } from '@/store/notificationStore'

type Mode = 'signin' | 'request' | 'forgot' | 'reset'

function resetTokenFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get('token')
}

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
  const resetToken = resetTokenFromUrl()
  const [mode, setMode] = useState<Mode>(resetToken ? 'reset' : 'signin')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [request, setRequest] = useState(EMPTY_REQUEST)
  const [submitted, setSubmitted] = useState<AccessRequest | null>(null)
  const [requestError, setRequestError] = useState('')

  const [forgotEmail, setForgotEmail] = useState('')
  const [forgotSent, setForgotSent] = useState(false)
  const [forgotBusy, setForgotBusy] = useState(false)
  const [forgotError, setForgotError] = useState('')

  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [resetBusy, setResetBusy] = useState(false)
  const [resetError, setResetError] = useState('')
  const [resetDone, setResetDone] = useState(false)

  useEffect(() => {
    if (resetToken) setMode('reset')
  }, [resetToken])

  const submitLogin = (event?: React.FormEvent) => {
    event?.preventDefault()
    if (!username.trim() || !password || isLoading) return
    login(username.trim(), password)
  }

  const submitForgotPassword = async (event?: React.FormEvent) => {
    event?.preventDefault()
    setForgotError('')
    if (!forgotEmail.trim()) return
    setForgotBusy(true)
    try {
      await api.post('/api/auth/forgot-password', { email: forgotEmail.trim() })
      setForgotSent(true)
    } catch (failure: any) {
      setForgotError(failure.response?.data?.detail ?? 'Failed to send reset email. Please try again.')
    } finally {
      setForgotBusy(false)
    }
  }

  const submitResetPassword = async (event?: React.FormEvent) => {
    event?.preventDefault()
    setResetError('')
    if (!resetToken) return
    if (newPassword !== confirmPassword) {
      setResetError('Passwords do not match.')
      return
    }
    setResetBusy(true)
    try {
      await api.post('/api/auth/reset-password', { token: resetToken, new_password: newPassword })
      setResetDone(true)
    } catch (failure: any) {
      setResetError(failure.response?.data?.detail ?? 'Reset link is invalid or has expired.')
    } finally {
      setResetBusy(false)
    }
  }

  const backToSignInAfterReset = () => {
    window.history.replaceState({}, '', window.location.pathname)
    setMode('signin')
  }

  const submitRequest = async (event?: React.FormEvent) => {
    event?.preventDefault()
    setRequestError('')
    if (!request.username.trim() || !request.full_name.trim() || !request.email.trim()) {
      setRequestError('Name, username, and email are required.')
      return
    }
    try {
      await api.post('/api/auth/request-access', {
        username: request.username.trim(),
        full_name: request.full_name.trim(),
        email: request.email.trim(),
        mobile: request.mobile.trim() || undefined,
        requested_role: request.requested_role,
        reason: request.reason.trim() || undefined,
      })
      const preview: AccessRequest = {
        id: '',
        username: request.username.trim(),
        full_name: request.full_name.trim(),
        email: request.email.trim(),
        mobile: request.mobile.trim(),
        requested_role: request.requested_role,
        reason: request.reason.trim(),
        status: 'pending',
        created_at: new Date().toISOString(),
      }
      notify.info('Access request submitted', `${preview.full_name} requested ${preview.requested_role} access`)
      setSubmitted(preview)
      setRequest(EMPTY_REQUEST)
    } catch (requestFailure: any) {
      setRequestError(requestFailure.response?.data?.detail ?? 'Failed to submit request. Please try again.')
    }
  }

  const switchMode = (nextMode: Mode) => {
    setMode(nextMode)
    setRequestError('')
  }

  const requestField = (
    key: keyof typeof EMPTY_REQUEST,
    label: string,
    icon: React.ReactNode,
    type = 'text',
    required = false,
  ) => (
    <label className="da-field">
      <span className="da-field-label">{label}{required ? ' *' : ''}</span>
      <span className="da-input-shell">
        <span className="da-input-icon">{icon}</span>
        <input
          type={type}
          className="da-input da-input-embedded"
          value={request[key]}
          required={required}
          onChange={event => setRequest(previous => ({ ...previous, [key]: event.target.value }))}
        />
      </span>
    </label>
  )

  return (
    <main className="da-login-page">
      <div className="da-login-image" aria-hidden="true" />
      <div className="da-login-shade" aria-hidden="true" />

      <section className="da-login-story" aria-label="DroneArjuna">
        <div className="da-login-brand">
          <span className="da-brand-mark da-brand-mark-light">DA</span>
          <span>
            <span className="block text-sm font-semibold text-white">DroneArjuna</span>
            <span className="block text-[10px] uppercase text-slate-300">Ground Control System</span>
          </span>
        </div>

        <div className="da-login-story-copy">
          <span className="da-login-status"><Radio size={13} /> Operations console</span>
          <h1>Command every mission with clarity.</h1>
          <p>Secure access to fleet readiness, mission planning, live flight control, and telemetry.</p>
        </div>

        <div className="da-login-trust">
          <ShieldCheck size={16} /> Authenticated mission environment
        </div>
      </section>

      <div className="da-login-form-region">
        <section className={`da-login-card ${mode === 'request' ? 'is-request' : ''}`}>
          <div className="mb-5">
            <span className="da-login-mobile-brand">DroneArjuna</span>
            <h2 className="da-login-card-title text-2xl font-bold leading-tight">
              {mode === 'signin' ? 'Welcome back'
                : mode === 'forgot' ? 'Reset your password'
                : mode === 'reset' ? 'Choose a new password'
                : 'Request access'}
            </h2>
            <p className="da-login-card-subtitle mt-1 text-sm">
              {mode === 'signin' ? 'Sign in to continue to the operations console.'
                : mode === 'forgot' ? 'Enter your account email — we\'ll send a reset link.'
                : mode === 'reset' ? 'Set a new password for your account.'
                : 'Send your details to an administrator for review.'}
            </p>
          </div>

          {(mode === 'signin' || mode === 'request') && (
          <div className="da-login-tabs" role="tablist" aria-label="Authentication options">
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'signin'}
              onClick={() => switchMode('signin')}
              className={mode === 'signin' ? 'is-active' : ''}>
              Sign in
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'request'}
              onClick={() => switchMode('request')}
              className={mode === 'request' ? 'is-active' : ''}>
              Request access
            </button>
          </div>
          )}

          {mode === 'signin' ? (
            <form onSubmit={submitLogin} className="flex flex-col gap-4">
              <label className="da-field">
                <span className="da-field-label">Username</span>
                <span className="da-input-shell">
                  <span className="da-input-icon"><User size={16} /></span>
                  <input
                    className="da-input da-input-embedded"
                    value={username}
                    onChange={event => setUsername(event.target.value)}
                    autoComplete="username"
                    autoFocus
                    required
                  />
                </span>
              </label>

              <label className="da-field">
                <span className="da-field-label">Password</span>
                <span className="da-input-shell">
                  <span className="da-input-icon"><Lock size={16} /></span>
                  <input
                    type={showPassword ? 'text' : 'password'}
                    className="da-input da-input-embedded pr-11"
                    value={password}
                    onChange={event => setPassword(event.target.value)}
                    autoComplete="current-password"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(value => !value)}
                    className="da-password-toggle"
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                    title={showPassword ? 'Hide password' : 'Show password'}>
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </span>
              </label>

              {error && <p className="da-form-error" role="alert">{error}</p>}

              <button
                type="submit"
                disabled={isLoading || !username.trim() || !password}
                className="da-btn da-btn-primary h-11 justify-center text-sm font-semibold">
                {isLoading ? 'Signing in...' : <>Sign in <ArrowRight size={15} /></>}
              </button>

              <button
                type="button"
                onClick={() => switchMode('forgot')}
                className="da-link text-xs self-center">
                Forgot password?
              </button>
            </form>
          ) : mode === 'forgot' ? (
            <form onSubmit={submitForgotPassword} className="flex flex-col gap-4">
              {forgotSent ? (
                <div className="da-request-success rounded-lg p-4 text-sm">
                  <div className="mb-3 flex items-center gap-2 font-semibold">
                    <CheckCircle2 size={17} /> Reset link sent
                  </div>
                  <p className="mb-3">If that email is registered, a password reset link has been sent to it. Check your inbox (or MailHog in dev).</p>
                  <button type="button" className="da-btn da-btn-primary text-xs" onClick={() => switchMode('signin')}>
                    Back to sign in
                  </button>
                </div>
              ) : (
                <>
                  <label className="da-field">
                    <span className="da-field-label">Email</span>
                    <span className="da-input-shell">
                      <span className="da-input-icon"><Mail size={16} /></span>
                      <input
                        type="email"
                        className="da-input da-input-embedded"
                        value={forgotEmail}
                        onChange={event => setForgotEmail(event.target.value)}
                        autoComplete="email"
                        autoFocus
                        required
                      />
                    </span>
                  </label>

                  {forgotError && <p className="da-form-error" role="alert">{forgotError}</p>}

                  <button
                    type="submit"
                    disabled={forgotBusy || !forgotEmail.trim()}
                    className="da-btn da-btn-primary h-11 justify-center text-sm font-semibold">
                    {forgotBusy ? 'Sending...' : <>Send reset link <ArrowRight size={15} /></>}
                  </button>

                  <button
                    type="button"
                    onClick={() => switchMode('signin')}
                    className="da-link text-xs self-center">
                    Back to sign in
                  </button>
                </>
              )}
            </form>
          ) : mode === 'reset' ? (
            <form onSubmit={submitResetPassword} className="flex flex-col gap-4">
              {resetDone ? (
                <div className="da-request-success rounded-lg p-4 text-sm">
                  <div className="mb-3 flex items-center gap-2 font-semibold">
                    <CheckCircle2 size={17} /> Password updated
                  </div>
                  <p className="mb-3">You can now sign in with your new password.</p>
                  <button type="button" className="da-btn da-btn-primary text-xs" onClick={backToSignInAfterReset}>
                    Back to sign in
                  </button>
                </div>
              ) : (
                <>
                  <label className="da-field">
                    <span className="da-field-label">New password</span>
                    <span className="da-input-shell">
                      <span className="da-input-icon"><KeyRound size={16} /></span>
                      <input
                        type={showPassword ? 'text' : 'password'}
                        className="da-input da-input-embedded pr-11"
                        value={newPassword}
                        onChange={event => setNewPassword(event.target.value)}
                        autoComplete="new-password"
                        autoFocus
                        required
                      />
                      <button
                        type="button"
                        onClick={() => setShowPassword(value => !value)}
                        className="da-password-toggle"
                        aria-label={showPassword ? 'Hide password' : 'Show password'}
                        title={showPassword ? 'Hide password' : 'Show password'}>
                        {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                      </button>
                    </span>
                  </label>

                  <label className="da-field">
                    <span className="da-field-label">Confirm password</span>
                    <span className="da-input-shell">
                      <span className="da-input-icon"><KeyRound size={16} /></span>
                      <input
                        type={showPassword ? 'text' : 'password'}
                        className="da-input da-input-embedded"
                        value={confirmPassword}
                        onChange={event => setConfirmPassword(event.target.value)}
                        autoComplete="new-password"
                        required
                      />
                    </span>
                  </label>

                  {resetError && <p className="da-form-error" role="alert">{resetError}</p>}

                  <button
                    type="submit"
                    disabled={resetBusy || !newPassword || !confirmPassword}
                    className="da-btn da-btn-primary h-11 justify-center text-sm font-semibold">
                    {resetBusy ? 'Updating...' : <>Update password <ArrowRight size={15} /></>}
                  </button>
                </>
              )}
            </form>
          ) : (
            <form onSubmit={submitRequest} className="flex flex-col gap-3">
              {submitted ? (
                <div className="da-request-success rounded-lg p-4 text-sm">
                  <div className="mb-3 flex items-center gap-2 font-semibold">
                    <CheckCircle2 size={17} /> Request queued for review
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <a className="da-btn da-btn-ghost text-xs" href={requestMailto(submitted)}><Mail size={13} /> Email</a>
                    {submitted.mobile && (
                      <a className="da-btn da-btn-ghost text-xs" href={requestSms(submitted)}><Phone size={13} /> SMS</a>
                    )}
                    <button type="button" className="da-btn da-btn-primary text-xs" onClick={() => setSubmitted(null)}>
                      New request
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {requestField('full_name', 'Full name', <User size={15} />, 'text', true)}
                    {requestField('username', 'Username', <UserPlus size={15} />, 'text', true)}
                    {requestField('email', 'Email', <Mail size={15} />, 'email', true)}
                    {requestField('mobile', 'Mobile', <Phone size={15} />)}
                  </div>

                  <label className="da-field">
                    <span className="da-field-label">Requested role *</span>
                    <select
                      className="da-input h-11"
                      value={request.requested_role}
                      onChange={event => setRequest(previous => ({ ...previous, requested_role: event.target.value }))}>
                      {REQUEST_ROLES.map(role => <option key={role} value={role}>{role}</option>)}
                    </select>
                  </label>

                  <label className="da-field">
                    <span className="da-field-label">Reason</span>
                    <textarea
                      className="da-input min-h-20"
                      rows={2}
                      value={request.reason}
                      onChange={event => setRequest(previous => ({ ...previous, reason: event.target.value }))}
                    />
                  </label>

                  {requestError && <p className="da-form-error" role="alert">{requestError}</p>}

                  <button type="submit" className="da-btn da-btn-primary h-11 justify-center text-sm font-semibold">
                    Submit request <ArrowRight size={15} />
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
