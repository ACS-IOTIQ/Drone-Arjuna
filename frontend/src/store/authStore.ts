// ═══════════════════════════════════════════
// src/store/authStore.ts
// Sessions are HttpOnly cookies managed by the backend; nothing secret is
// stored in (or readable from) JavaScript.
// ═══════════════════════════════════════════
import { create } from 'zustand'
import { login as apiLogin, verifyMfa as apiVerifyMfa, getMe, logoutRequest, type LoginResponse } from '@/api/auth'
import { notify } from '@/store/notificationStore'
import {
  getPasswordSetupState,
  clearPasswordSetupState,
  setPasswordSetupState,
  purgeLegacyAuthStorage,
} from '@/store/accessRequestStore'

interface AuthState {
  /** True once the server has accepted the HttpOnly session cookie. */
  authenticated: boolean
  /** False until the first session check on page load has finished. */
  ready: boolean
  user: Record<string, unknown> | null
  role: string
  isLoading: boolean
  error: string
  setupPending: boolean
  pendingUsername: string | null
  pendingTempPassword: string | null
  pendingEmail: string | null
  pendingMobile: string | null
  /** Set after the password step when a second factor is required. */
  mfaToken: string | null
  login: (u: string, p: string) => Promise<void>
  verifyMfa: (code: string) => Promise<void>
  cancelMfa: () => void
  logout: () => Promise<void>
  /** Local-only teardown (session already gone server-side). */
  expireSession: () => void
  hydrate: () => Promise<void>
  completePasswordSetup: () => void
}

purgeLegacyAuthStorage()
// Kept only in memory, only between the password step and the MFA step.
let lastCredentials: { username: string; password: string } | null = null

function describeAuthError(e: any): string {
  const status = e?.response?.status
  const detail = e?.response?.data?.detail
  console.error('Login error:', e)
  return status === 401
    ? 'Invalid username or password'
    : status === 429
    ? 'Too many failed attempts. Try again later.'
    : detail
    ? `Error: ${detail}`
    : e?.message
    ? `Network error: ${e.message}`
    : 'Login failed — check console for details'
}

async function finishLogin(
  res: LoginResponse,
  username: string,
  password: string,
  set: (partial: Partial<AuthState>) => void,
) {
  const isTemp = Boolean(res.must_change_password)
  let pendingEmail: string | null = null
  if (isTemp) {
    // Fetch user profile to get email for the PasswordSetupScreen greeting
    try {
      const me = await getMe()
      pendingEmail = me.email ?? null
    } catch { /* non-critical — screen still works without email */ }
    setPasswordSetupState({ username, tempPassword: password, email: pendingEmail ?? '', mobile: '' })
  } else {
    clearPasswordSetupState()
  }

  set({
    authenticated: true,
    ready: true,
    mfaToken: null,
    role: res.role ?? 'viewer',
    isLoading: false,
    setupPending: isTemp,
    pendingUsername: isTemp ? username : null,
    pendingTempPassword: isTemp ? password : null,
    pendingEmail,
    pendingMobile: null,
  })

  if (res.mfa_enrollment_required) {
    notify.warning(
      'Multi-factor authentication required',
      'Your role requires MFA. Enable it under Settings → Security.',
    )
  }
}

const pendingSetup = getPasswordSetupState()

export const useAuthStore = create<AuthState>((set) => ({
  authenticated: false,
  ready: false,
  mfaToken: null,
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
      if (res.mfa_required && res.mfa_token) {
        // Password accepted; ask for the authenticator / recovery code next.
        lastCredentials = { username, password }
        set({ mfaToken: res.mfa_token, isLoading: false })
        return
      }
      await finishLogin(res, username, password, set)
    } catch (e: any) {
      set({ error: describeAuthError(e), isLoading: false })
    }
  },

  verifyMfa: async (code) => {
    const token = useAuthStore.getState().mfaToken
    if (!token) return
    set({ isLoading: true, error: '' })
    try {
      const res = await apiVerifyMfa(token, code.trim())
      const creds = lastCredentials ?? { username: '', password: '' }
      lastCredentials = null
      await finishLogin(res, creds.username, creds.password, set)
    } catch (e: any) {
      const status = e?.response?.status
      const msg = status === 429
        ? 'Too many attempts. Try again later.'
        : status === 401
        ? 'Invalid code. Check your authenticator app, or use a recovery code.'
        : describeAuthError(e)
      // an expired/used challenge cannot be retried: go back to the password step
      if (status === 401 && /validate credentials/i.test(String(e?.response?.data?.detail ?? ''))) {
        lastCredentials = null
        set({ mfaToken: null, error: 'Sign-in timed out. Please sign in again.', isLoading: false })
        return
      }
      set({ error: msg, isLoading: false })
    }
  },

  cancelMfa: () => {
    lastCredentials = null
    set({ mfaToken: null, error: '', isLoading: false })
  },

  logout: async () => {
    try { await logoutRequest() } catch { /* session may already be gone */ }
    useAuthStore.getState().expireSession()
  },

  expireSession: () => {
    clearPasswordSetupState()
    set({
      authenticated: false, ready: true, user: null, role: 'viewer',
      setupPending: false, pendingUsername: null, pendingTempPassword: null,
      pendingEmail: null, pendingMobile: null,
    })
  },

  hydrate: async () => {
    try {
      const user = await getMe()
      // A temporary password only lives in memory; after a reload the forced
      // password-change flow cannot be resumed, so send the user back to sign in.
      if (user.must_change_password && !getPasswordSetupState()) {
        await useAuthStore.getState().logout()
        return
      }
      set({ user, role: user.role, authenticated: true, ready: true })
    } catch {
      useAuthStore.getState().expireSession()
    }
  },

  completePasswordSetup: () => {
    // The password change revokes all sessions server-side; sign in again.
    useAuthStore.getState().expireSession()
  },
}))
