// ═══════════════════════════════════════════
// src/store/authStore.ts
// ═══════════════════════════════════════════
import { create } from 'zustand'
import { login as apiLogin, getMe } from '@/api/auth'
import {
  getPasswordSetupState,
  findApprovedAccessRequest,
  clearPasswordSetupState,
  setPasswordSetupState,
} from '@/store/accessRequestStore'

interface AuthState {
  token: string | null
  user: Record<string, unknown> | null
  role: string
  isLoading: boolean
  error: string
  setupPending: boolean
  pendingUsername: string | null
  pendingTempPassword: string | null
  pendingEmail: string | null
  pendingMobile: string | null
  login: (u: string, p: string) => Promise<void>
  logout: () => void
  hydrate: () => Promise<void>
  completePasswordSetup: () => void
}

const pendingSetup = getPasswordSetupState()

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem('da_token'),
  user: null,
  role: 'viewer',
  isLoading: false,
  error: '',
  setupPending: Boolean(pendingSetup),
  pendingUsername: pendingSetup?.username ?? null,
  pendingTempPassword: pendingSetup?.tempPassword ?? null,
  pendingEmail: pendingSetup?.email ?? null,
  pendingMobile: pendingSetup?.mobile ?? null,

  login: async (username, password) => {
    set({ isLoading: true, error: '' })
    try {
      const res = await apiLogin(username, password)
      localStorage.setItem('da_token', res.access_token)

      const approved = findApprovedAccessRequest(username, password)
      const isTemp = Boolean(approved)
      if (isTemp && approved) {
        setPasswordSetupState({
          username,
          tempPassword: password,
          email: approved.email,
          mobile: approved.mobile,
        })
      } else {
        clearPasswordSetupState()
      }

      set({
        token: res.access_token,
        role: res.role,
        isLoading: false,
        setupPending: isTemp,
        pendingUsername: isTemp ? username : null,
        pendingTempPassword: isTemp ? password : null,
        pendingEmail: isTemp ? approved?.email ?? null : null,
        pendingMobile: isTemp ? approved?.mobile ?? null : null,
      })
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
    clearPasswordSetupState()
    set({ token: null, user: null, role: 'viewer', setupPending: false, pendingUsername: null, pendingTempPassword: null, pendingEmail: null, pendingMobile: null })
  },

  hydrate: async () => {
    try {
      const user = await getMe()
      set({ user, role: user.role })
    } catch {
      localStorage.removeItem('da_token')
      clearPasswordSetupState()
      set({ token: null, setupPending: false, pendingUsername: null, pendingTempPassword: null, pendingEmail: null, pendingMobile: null })
    }
  },

  completePasswordSetup: () => {
    clearPasswordSetupState()
    localStorage.removeItem('da_token')
    set({ token: null, user: null, role: 'viewer', setupPending: false, pendingUsername: null, pendingTempPassword: null, pendingEmail: null, pendingMobile: null })
  },
}))
