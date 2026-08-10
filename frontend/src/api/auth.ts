
// ═══════════════════════════════════════════
// src/api/auth.ts
// ═══════════════════════════════════════════
import { api } from './client'

export interface LoginResponse {
  access_token: string
  token_type: string
  role: string
  must_change_password: boolean
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const form = new URLSearchParams({ username, password })
  const { data } = await api.post<LoginResponse>('/api/auth/token', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  return data
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
