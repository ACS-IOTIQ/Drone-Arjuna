
// ═══════════════════════════════════════════
// src/api/auth.ts
// ═══════════════════════════════════════════
import { api } from './client'

export interface LoginResponse {
  access_token: string
  token_type: string
  role: string
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