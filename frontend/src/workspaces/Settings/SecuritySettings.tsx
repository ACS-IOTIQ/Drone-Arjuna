import { useEffect, useState } from 'react'
import QRCode from 'qrcode'
import { ShieldCheck, ShieldOff } from 'lucide-react'
import {
  getMe, mfaSetup, mfaEnable, mfaDisable, mfaRegenerateRecoveryCodes,
} from '@/api/auth'
import { notify } from '@/store/notificationStore'

type Phase = 'idle' | 'enrolling' | 'disabling'

function errorText(e: any, fallback: string): string {
  return e?.response?.data?.detail ?? fallback
}

export default function SecuritySettings() {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [secret, setSecret] = useState('')
  const [qr, setQr] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const refresh = () =>
    getMe().then(me => setEnabled(Boolean(me.totp_enabled))).catch(() => setEnabled(null))

  useEffect(() => { refresh() }, [])

  const reset = () => {
    setPhase('idle'); setSecret(''); setQr(''); setCode(''); setPassword(''); setError('')
  }

  const startEnrol = async () => {
    setBusy(true); setError('')
    try {
      const { secret: s, otpauth_uri } = await mfaSetup()
      setSecret(s)
      setQr(await QRCode.toDataURL(otpauth_uri, { margin: 1, width: 192 }))
      setPhase('enrolling')
    } catch (e) {
      setError(errorText(e, 'Could not start MFA setup.'))
    } finally {
      setBusy(false)
    }
  }

  const confirmEnrol = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true); setError('')
    try {
      const { recovery_codes } = await mfaEnable(code.trim())
      setRecoveryCodes(recovery_codes)
      notify.success('MFA enabled', 'Two-step verification is now required at sign-in.')
      reset()
      await refresh()
    } catch (e) {
      setError(errorText(e, 'Invalid code. Check your authenticator app and try again.'))
    } finally {
      setBusy(false)
    }
  }

  const confirmDisable = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true); setError('')
    try {
      await mfaDisable(password, code.trim())
      notify.warning('MFA disabled', 'Your account is protected by password only.')
      setRecoveryCodes([])
      reset()
      await refresh()
    } catch (e) {
      setError(errorText(e, 'Could not disable MFA. Check your password and code.'))
    } finally {
      setBusy(false)
    }
  }

  const regenerate = async () => {
    const entered = window.prompt('Enter a code from your authenticator app to generate new recovery codes:')
    if (!entered) return
    try {
      const { recovery_codes } = await mfaRegenerateRecoveryCodes(entered.trim())
      setRecoveryCodes(recovery_codes)
    } catch (e) {
      notify.danger('Could not regenerate codes', errorText(e, 'Invalid code.'))
    }
  }

  return (
    <div className="flex max-w-xl flex-col gap-4">
      <div>
        <h2 className="mb-1 text-lg font-semibold">Security</h2>
        <p className="text-sm" style={{ color: '#6b7280' }}>
          Protect your account with a time-based one-time code from an authenticator app
          (Google Authenticator, Microsoft Authenticator, Aegis, …).
        </p>
      </div>

      <div className="da-card flex flex-col gap-3 p-4">
        <div className="flex items-center gap-2 text-sm font-semibold">
          {enabled ? <ShieldCheck size={16} /> : <ShieldOff size={16} />}
          Two-step verification: {enabled === null ? 'unknown' : enabled ? 'on' : 'off'}
        </div>

        {phase === 'idle' && enabled === false && (
          <button className="da-btn da-btn-primary self-start" onClick={startEnrol} disabled={busy}>
            Set up two-step verification
          </button>
        )}

        {phase === 'idle' && enabled && (
          <div className="flex flex-wrap gap-2">
            <button className="da-btn da-btn-ghost" onClick={regenerate}>New recovery codes</button>
            <button className="da-btn da-btn-ghost" onClick={() => { setPhase('disabling'); setError('') }}>
              Turn off
            </button>
          </div>
        )}

        {phase === 'enrolling' && (
          <form onSubmit={confirmEnrol} className="flex flex-col gap-3">
            <p className="text-sm">1. Scan this QR code with your authenticator app:</p>
            {qr && <img src={qr} alt="MFA QR code" width={192} height={192} className="self-start rounded bg-white p-1" />}
            <p className="text-xs" style={{ color: '#6b7280' }}>
              Can’t scan? Enter this key manually: <code className="select-all break-all">{secret}</code>
            </p>
            <p className="text-sm">2. Enter the 6-digit code it shows:</p>
            <input
              className="da-input w-40 tracking-widest"
              value={code}
              onChange={e => setCode(e.target.value)}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={8}
              autoFocus
              required
            />
            {error && <p className="da-form-error" role="alert">{error}</p>}
            <div className="flex gap-2">
              <button type="submit" className="da-btn da-btn-primary" disabled={busy || !code.trim()}>
                Verify and enable
              </button>
              <button type="button" className="da-btn da-btn-ghost" onClick={reset}>Cancel</button>
            </div>
          </form>
        )}

        {phase === 'disabling' && (
          <form onSubmit={confirmDisable} className="flex flex-col gap-3">
            <p className="text-sm">Confirm with your password and a current code (or a recovery code).</p>
            <input
              type="password"
              className="da-input"
              placeholder="Password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
            <input
              className="da-input w-40 tracking-widest"
              placeholder="Code"
              value={code}
              onChange={e => setCode(e.target.value)}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={32}
              required
            />
            {error && <p className="da-form-error" role="alert">{error}</p>}
            <div className="flex gap-2">
              <button type="submit" className="da-btn da-btn-primary" disabled={busy || !password || !code.trim()}>
                Turn off
              </button>
              <button type="button" className="da-btn da-btn-ghost" onClick={reset}>Cancel</button>
            </div>
          </form>
        )}

        {phase === 'idle' && error && <p className="da-form-error" role="alert">{error}</p>}
      </div>

      {recoveryCodes.length > 0 && (
        <div className="da-card flex flex-col gap-2 p-4">
          <p className="text-sm font-semibold">Recovery codes — save them now</p>
          <p className="text-xs" style={{ color: '#6b7280' }}>
            Each code works once if you lose your authenticator. They are not shown again.
          </p>
          <ul className="grid grid-cols-2 gap-1 font-mono text-sm">
            {recoveryCodes.map(c => <li key={c} className="select-all">{c}</li>)}
          </ul>
          <button
            className="da-btn da-btn-ghost self-start"
            onClick={() => { navigator.clipboard?.writeText(recoveryCodes.join('\n')); notify.info('Copied', 'Recovery codes copied.') }}>
            Copy
          </button>
          <button className="da-btn da-btn-ghost self-start" onClick={() => setRecoveryCodes([])}>
            I have saved them
          </button>
        </div>
      )}
    </div>
  )
}
