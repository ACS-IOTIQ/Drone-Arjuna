// ═══════════════════════════════════════════
// src/api/client.ts  — Axios base instance
// ═══════════════════════════════════════════
import axios from 'axios'

// Use relative URLs so all requests go through the Vite proxy.
// Vite proxy maps /api → http://backend:8000 and /ws → ws://backend:8000
// This avoids CORS entirely since browser and API appear on the same origin.
export const api = axios.create({ baseURL: '', timeout: 12000 })

// Attach JWT from localStorage on every request
api.interceptors.request.use(cfg => {
  const token = localStorage.getItem('da_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// On 401 → clear token and reload
api.interceptors.response.use(
  r => r,
  err => {
    const requestUrl = String(err.config?.url ?? '')
    const isLoginRequest = requestUrl.includes('/api/auth/token')
    if (err.response?.status === 401 && !isLoginRequest) {
      localStorage.removeItem('da_token')
      window.dispatchEvent(new Event('da_auth_expired'))
    }
    return Promise.reject(err)
  }
)

export function makeTelemetryWS(droneId: number): WebSocket {
  const token = localStorage.getItem('da_token') ?? ''
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host  = window.location.host
  // Route through the /api proxy (ws: true) — backend endpoint is /api/drone-control/stream/{id}
  return new WebSocket(`${proto}//${host}/api/drone-control/stream/${droneId}?token=${token}`)
}

export function makeTelemetryUrl(droneId: number): string {
  const token = localStorage.getItem('da_token') ?? ''
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host  = window.location.host
  return `${proto}//${host}/api/drone-control/stream/${droneId}?token=${token}`
}
