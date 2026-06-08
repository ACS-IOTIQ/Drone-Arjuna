// ═══════════════════════════════════════════
// src/store/authStore.ts
// ═══════════════════════════════════════════
import { create } from 'zustand'
import { login as apiLogin, getMe } from '@/api/auth'

interface AuthState {
  token: string | null
  user: Record<string, unknown> | null
  role: string
  isLoading: boolean
  error: string
  login: (u: string, p: string) => Promise<void>
  logout: () => void
  hydrate: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem('da_token'),
  user: null,
  role: 'viewer',
  isLoading: false,
  error: '',

  login: async (username, password) => {
    set({ isLoading: true, error: '' })
    try {
      const res = await apiLogin(username, password)
      localStorage.setItem('da_token', res.access_token)
      set({ token: res.access_token, role: res.role, isLoading: false })
    } catch (e: any) {
      const status = e?.response?.status
      const detail = e?.response?.data?.detail
      const msg = status === 401
        ? 'Invalid username or password'
        : detail
        ? `Error: ${detail}`
        : e?.message
        ? `Network error: ${e.message}`
        : 'Login failed — check console for details'
      console.error('Login error:', e)
      set({ error: msg, isLoading: false })
    }
  },

  logout: () => {
    localStorage.removeItem('da_token')
    set({ token: null, user: null, role: 'viewer' })
  },

  hydrate: async () => {
    try {
      const user = await getMe()
      set({ user, role: user.role })
    } catch {
      localStorage.removeItem('da_token')
      set({ token: null })
    }
  },
}))
