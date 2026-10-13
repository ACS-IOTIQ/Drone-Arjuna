
// ═══════════════════════════════════════════
// src/api/auth.ts
// ═══════════════════════════════════════════
import { api } from './client'

// Either a finished sign-in, or (mfa_required) a challenge: the password was
// accepted but a second factor is still needed and no session exists yet.
export interface LoginResponse {
  token_type?: string
  role?: string
  must_change_password?: boolean
  mfa_enrollment_required?: boolean
  mfa_required?: boolean
  mfa_token?: string
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const form = new URLSearchParams({ username, password })
  const { data } = await api.post<LoginResponse>('/api/auth/token', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  return data
}

export async function verifyMfa(mfaToken: string, code: string): Promise<LoginResponse> {
  const { data } = await api.post<LoginResponse>('/api/auth/mfa/verify', { mfa_token: mfaToken, code })
  return data
}

export async function mfaSetup() {
  const { data } = await api.post<{ secret: string; otpauth_uri: string }>('/api/auth/mfa/setup')
  return data
}

export async function mfaEnable(code: string) {
  const { data } = await api.post<{ recovery_codes: string[] }>('/api/auth/mfa/enable', { code })
  return data
}

export async function mfaDisable(password: string, code: string) {
  await api.post('/api/auth/mfa/disable', { password, code })
}

export async function mfaRegenerateRecoveryCodes(code: string) {
  const { data } = await api.post<{ recovery_codes: string[] }>('/api/auth/mfa/recovery-codes', { code })
  return data
}

export async function logoutRequest() {
  await api.post('/api/auth/logout', {})
}

export async function getMe() {
  const { data } = await api.get('/api/auth/me')
  return data
}

export async function forgotPassword(email: string) {
  const { data } = await api.post('/api/auth/forgot-password', { email })
  return data as { message: string }
}

export async function resetPassword(token: string, newPassword: string) {
  const { data } = await api.post('/api/auth/reset-password', {
    token,
    new_password: newPassword,
  })
  return data as { message: string }
}
