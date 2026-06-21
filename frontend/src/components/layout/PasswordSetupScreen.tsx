import { useState } from 'react'
import { Eye, EyeOff, Lock, Shield } from 'lucide-react'

interface PasswordSetupScreenProps {
  username: string
  tempPassword: string
  onSetupComplete: (newPassword: string) => void
}

export default function PasswordSetupScreen({
  username,
  tempPassword,
  onSetupComplete,
}: PasswordSetupScreenProps) {
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [passwordError, setPasswordError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const validatePassword = (pwd: string): string | null => {
    if (pwd.length < 8) return 'Password must be at least 8 characters'
    if (!/[A-Z]/.test(pwd)) return 'Must contain uppercase letter'
    if (!/[a-z]/.test(pwd)) return 'Must contain lowercase letter'
    if (!/[0-9]/.test(pwd)) return 'Must contain number'
    if (!/[!@#$%^&*]/.test(pwd)) return 'Must contain special character (!@#$%^&*)'
    return null
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setPasswordError('')

    const validationError = validatePassword(password)
    if (validationError) {
      setPasswordError(validationError)
      return
    }

    if (password !== confirmPassword) {
      setPasswordError('Passwords do not match')
      return
    }

    setIsLoading(true)
    try {
      // Simulate API call - replace with actual backend call
      await new Promise(resolve => setTimeout(resolve, 500))
      onSetupComplete(password)
    } catch (error) {
      setPasswordError('Failed to set password. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }

  const strengthIndicator = (pwd: string) => {
    let strength = 0
    if (pwd.length >= 8) strength++
    if (/[A-Z]/.test(pwd)) strength++
    if (/[a-z]/.test(pwd)) strength++
    if (/[0-9]/.test(pwd)) strength++
    if (/[!@#$%^&*]/.test(pwd)) strength++
    return strength
  }

  const strength = strengthIndicator(password)

  return (
    <main className="min-h-screen w-screen overflow-y-auto px-4 py-8 text-slate-950"
      style={{
        background: 'linear-gradient(135deg, #1e293b 0%, #0f172a 50%, #1e293b 100%)',
        position: 'relative',
      }}>
      {/* Animated background grid */}
      <div className="pointer-events-none absolute inset-0 opacity-10"
        style={{
          backgroundImage: 'radial-gradient(circle at 1px 1px, rgba(255,255,255,0.5) 1px, transparent 1px)',
          backgroundSize: '40px 40px',
        }} />

      <div className="mx-auto flex min-h-[calc(100vh-4rem)] w-full max-w-md items-center relative z-10">
        <section className="da-card w-full p-6 sm:p-8" style={{
          boxShadow: '0 20px 60px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.1)',
        }}>
          <div className="mb-6 text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-gradient-to-br from-blue-600 to-blue-700 text-white">
              <Shield size={28} />
            </div>
            <h1 className="text-2xl font-bold">Set Your Password</h1>
            <p className="mt-2 text-sm text-slate-600">
              Welcome, <span className="font-semibold text-slate-800">{username}</span>! Your access has been approved.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            {/* Temp Password Display */}
            <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
              <p className="text-xs font-semibold text-blue-900 mb-1">Temporary Password (for first login):</p>
              <div className="flex items-center gap-2 rounded bg-white p-2 border border-blue-100">
                <code className="flex-1 font-mono text-sm text-blue-900">{tempPassword}</code>
                <button
                  type="button"
                  onClick={() => {
                    navigator.clipboard.writeText(tempPassword)
                  }}
                  className="da-btn da-btn-ghost text-xs"
                >
                  Copy
                </button>
              </div>
              <p className="mt-2 text-xs text-blue-800">
                Keep this safe. You'll use it on your first login, then set a permanent password below.
              </p>
            </div>

            {/* New Password */}
            <label className="flex flex-col gap-2">
              <span className="text-sm font-semibold text-slate-700 leading-tight" style={{ letterSpacing: '0.5px', minHeight: '20px', display: 'block' }}>
                New Password *
              </span>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400 flex items-center" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  className="da-input pl-9 pr-10 py-2.5"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="Enter your new password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="pointer-events-auto absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </label>

            {/* Strength Indicator */}
            {password && (
              <div className="flex items-center gap-2">
                <div className="flex-1 h-2 bg-slate-200 rounded-full overflow-hidden">
                  <div
                    className={`h-full transition-all ${
                      strength === 5
                        ? 'bg-green-500'
                        : strength >= 3
                          ? 'bg-yellow-500'
                          : 'bg-red-500'
                    }`}
                    style={{ width: `${(strength / 5) * 100}%` }}
                  />
                </div>
                <span className="text-xs font-semibold text-slate-600">
                  {strength === 5 ? '✓ Strong' : strength >= 3 ? 'Fair' : 'Weak'}
                </span>
              </div>
            )}

            {/* Requirements Checklist */}
            {password && (
              <div className="rounded-lg bg-slate-50 p-3 border border-slate-200">
                <p className="text-xs font-semibold text-slate-700 mb-2">Requirements:</p>
                <div className="space-y-1 text-xs text-slate-600">
                  <div className={password.length >= 8 ? 'text-green-600' : ''}>
                    ✓ At least 8 characters
                  </div>
                  <div className={/[A-Z]/.test(password) ? 'text-green-600' : ''}>
                    ✓ Uppercase letter
                  </div>
                  <div className={/[a-z]/.test(password) ? 'text-green-600' : ''}>
                    ✓ Lowercase letter
                  </div>
                  <div className={/[0-9]/.test(password) ? 'text-green-600' : ''}>
                    ✓ Number
                  </div>
                  <div className={/[!@#$%^&*]/.test(password) ? 'text-green-600' : ''}>
                    ✓ Special character (!@#$%^&*)
                  </div>
                </div>
              </div>
            )}

            {/* Confirm Password */}
            <label className="flex flex-col gap-2">
              <span className="text-sm font-semibold text-slate-700 leading-tight" style={{ letterSpacing: '0.5px', minHeight: '20px', display: 'block' }}>
                Confirm Password *
              </span>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400 flex items-center" />
                <input
                  type={showConfirm ? 'text' : 'password'}
                  className="da-input pl-9 pr-10 py-2.5"
                  value={confirmPassword}
                  onChange={e => setConfirmPassword(e.target.value)}
                  placeholder="Confirm your password"
                />
                <button
                  type="button"
                  onClick={() => setShowConfirm(!showConfirm)}
                  className="pointer-events-auto absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                >
                  {showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </label>

            {/* Match Indicator */}
            {confirmPassword && (
              <div className={`text-xs font-semibold ${password === confirmPassword ? 'text-green-600' : 'text-red-600'}`}>
                {password === confirmPassword ? '✓ Passwords match' : '✗ Passwords do not match'}
              </div>
            )}

            {/* Error Message */}
            {passwordError && (
              <p className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {passwordError}
              </p>
            )}

            {/* Submit Button */}
            <button
              type="submit"
              disabled={isLoading || !password || !confirmPassword || strength < 5}
              className="da-btn da-btn-primary justify-center py-3 text-sm font-semibold mt-4"
            >
              {isLoading ? 'Setting Password...' : 'Complete Setup'}
            </button>

            <p className="text-xs text-slate-500 text-center">
              After setup, use the temporary password to log in, then update your profile.
            </p>
          </form>
        </section>
      </div>
    </main>
  )
}
