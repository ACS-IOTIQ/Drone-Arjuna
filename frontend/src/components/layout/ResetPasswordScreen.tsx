import { useState } from 'react'
import { ArrowLeft, CheckCircle2, Eye, EyeOff, Lock, ShieldAlert } from 'lucide-react'
import { resetPassword } from '@/api/auth'

interface ResetPasswordScreenProps {
  token: string
  onDone: () => void
}

function validatePassword(pwd: string): string | null {
  if (pwd.length < 8) return 'Password must be at least 8 characters'
  if (!/[A-Z]/.test(pwd)) return 'Must contain uppercase letter'
  if (!/[a-z]/.test(pwd)) return 'Must contain lowercase letter'
  if (!/[0-9]/.test(pwd)) return 'Must contain number'
  if (!/[!@#$%^&*]/.test(pwd)) return 'Must contain special character (!@#$%^&*)'
  return null
}

export default function ResetPasswordScreen({ token, onDone }: ResetPasswordScreenProps) {
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [done, setDone] = useState(false)

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')

    const validationError = validatePassword(password)
    if (validationError) {
      setError(validationError)
      return
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }

    setIsLoading(true)
    try {
      await resetPassword(token, password)
      setDone(true)
    } catch (failure: any) {
      const detail = failure?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : detail?.message ?? 'Reset link is invalid or has expired.')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <main className="da-password-setup-page text-slate-950"
      style={{ background: 'linear-gradient(135deg, #1e293b 0%, #0f172a 50%, #1e293b 100%)' }}>
      <div className="pointer-events-none absolute inset-0 opacity-10"
        style={{
          backgroundImage: 'radial-gradient(circle at 1px 1px, rgba(255,255,255,0.5) 1px, transparent 1px)',
          backgroundSize: '40px 40px',
        }} />

      <div className="da-password-setup-content">
        <section className="da-card w-full p-6 sm:p-8" style={{
          boxShadow: '0 20px 60px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.1)',
        }}>
          {done ? (
            <div className="text-center">
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-600 to-emerald-700 text-white">
                <CheckCircle2 size={28} />
              </div>
              <h1 className="text-2xl font-bold">Password updated</h1>
              <p className="mt-2 text-sm text-slate-600">
                Your password has been changed. You can sign in with it now.
              </p>
              <button
                type="button"
                onClick={onDone}
                className="da-btn da-btn-primary mt-6 justify-center py-3 text-sm font-semibold w-full">
                Back to sign in
              </button>
            </div>
          ) : (
            <>
              <button
                type="button"
                onClick={onDone}
                disabled={isLoading}
                className="da-btn da-btn-ghost mb-5 text-xs font-semibold">
                <ArrowLeft size={15} /> Back to sign in
              </button>

              <div className="mb-6 text-center">
                <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-gradient-to-br from-blue-600 to-blue-700 text-white">
                  <Lock size={28} />
                </div>
                <h1 className="text-2xl font-bold">Choose a new password</h1>
                <p className="mt-2 text-sm text-slate-600">
                  This reset link expires 30 minutes after it was sent.
                </p>
              </div>

              <form onSubmit={handleSubmit} className="flex flex-col gap-4">
                <label className="flex flex-col gap-2">
                  <span className="text-sm font-semibold text-slate-700 leading-tight">New Password *</span>
                  <div className="da-input-shell">
                    <span className="da-input-icon"><Lock size={16} /></span>
                    <input
                      type={showPassword ? 'text' : 'password'}
                      className="da-input da-input-embedded da-password-input"
                      value={password}
                      onChange={e => setPassword(e.target.value)}
                      placeholder="Enter your new password"
                      autoComplete="new-password"
                      autoFocus
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(v => !v)}
                      className="da-password-toggle"
                      aria-label={showPassword ? 'Hide password' : 'Show password'}
                      title={showPassword ? 'Hide password' : 'Show password'}>
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </label>

                <label className="flex flex-col gap-2">
                  <span className="text-sm font-semibold text-slate-700 leading-tight">Confirm Password *</span>
                  <div className="da-input-shell">
                    <span className="da-input-icon"><Lock size={16} /></span>
                    <input
                      type={showConfirm ? 'text' : 'password'}
                      className="da-input da-input-embedded da-password-input"
                      value={confirmPassword}
                      onChange={e => setConfirmPassword(e.target.value)}
                      placeholder="Confirm your password"
                      autoComplete="new-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowConfirm(v => !v)}
                      className="da-password-toggle"
                      aria-label={showConfirm ? 'Hide confirmed password' : 'Show confirmed password'}
                      title={showConfirm ? 'Hide confirmed password' : 'Show confirmed password'}>
                      {showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </label>

                {confirmPassword && (
                  <div className={`text-xs font-semibold ${password === confirmPassword ? 'text-green-600' : 'text-red-600'}`}>
                    {password === confirmPassword ? '✓ Passwords match' : '✗ Passwords do not match'}
                  </div>
                )}

                {error && (
                  <p className="flex items-center gap-2 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                    <ShieldAlert size={15} /> {error}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={isLoading || !password || !confirmPassword}
                  className="da-btn da-btn-primary justify-center py-3 text-sm font-semibold mt-2">
                  {isLoading ? 'Updating...' : 'Reset password'}
                </button>
              </form>
            </>
          )}
        </section>
      </div>
    </main>
  )
}
