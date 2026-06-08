import { useState } from 'react'
import { useAuthStore } from '@/store/authStore'
import { Lock, User, Wifi } from 'lucide-react'

export default function LoginScreen() {
  const { login, isLoading, error } = useAuthStore()
  const [u, setU] = useState('')
  const [p, setP] = useState('')

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault()
    console.log('Login attempted with:', u, '/ [password hidden]')
    login(u, p)
  }

  return (
    <div className="h-screen w-screen flex items-center justify-center"
      style={{ background: 'linear-gradient(135deg, #0a0e1a 0%, #0d1526 100%)' }}>

      {/* Animated grid background */}
      <div className="absolute inset-0 opacity-10"
        style={{
          backgroundImage: 'linear-gradient(#3b82f6 1px, transparent 1px), linear-gradient(90deg, #3b82f6 1px, transparent 1px)',
          backgroundSize: '60px 60px',
        }} />

      <div className="relative z-10 w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl mb-4"
            style={{ background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.3)' }}>
            <Wifi className="w-8 h-8" style={{ color: '#3b82f6' }} />
          </div>
          <h1 className="text-2xl font-bold tracking-wide">DroneArjuna</h1>
          <p className="text-sm mt-1" style={{ color: '#6b7280' }}>Ground Control System</p>
        </div>

        {/* Card */}
        <div className="da-card p-8">
          <form onSubmit={submit} className="flex flex-col gap-4">
            <div>
              <label className="text-xs font-medium mb-1 block" style={{ color: '#94a3b8' }}>
                USERNAME
              </label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: '#6b7280' }} />
                <input
                  className="da-input pl-9"
                  placeholder="operator_01"
                  value={u}
                  onChange={e => setU(e.target.value)}
                  autoFocus
                />
              </div>
            </div>

            <div>
              <label className="text-xs font-medium mb-1 block" style={{ color: '#94a3b8' }}>
                PASSWORD
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: '#6b7280' }} />
                <input
                  type="password"
                  className="da-input pl-9"
                  placeholder="••••••••"
                  value={p}
                  onChange={e => setP(e.target.value)}
                />
              </div>
            </div>

            {error && (
              <p className="text-xs text-center py-2 px-3 rounded"
                style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.2)' }}>
                {error}
              </p>
            )}

            <button
              type="button"
              onClick={submit}
              disabled={isLoading || !u || !p}
              className="da-btn da-btn-primary justify-center py-3 mt-2 text-sm font-semibold">
              {isLoading ? 'Authenticating…' : 'Sign In'}
            </button>
          </form>
        </div>

        <p className="text-center text-xs mt-6" style={{ color: '#374151' }}>
          CLASSIFIED SYSTEM — AUTHORISED ACCESS ONLY
        </p>
      </div>
    </div>
  )
}