// ═══════════════════════════════════════════
// src/api/client.ts  — Axios base instance
// ═══════════════════════════════════════════
import axios from 'axios'

// Use relative URLs so all requests go through the Vite proxy.
// Vite proxy maps /api → http://backend:8000 and /ws → ws://backend:8000
// This avoids CORS entirely since browser and API appear on the same origin.
export const api = axios.create({ baseURL: '', timeout: 30000 })

// Attach JWT from localStorage on every request
api.interceptors.request.use(cfg => {
  const token = localStorage.getItem('da_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// On 401 → try a silent refresh (using the stored refresh_token) and retry the
// original request once. Only log the user out if the refresh itself fails
// (refresh token missing/expired) or the request has already been retried.
let refreshPromise: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  const refreshToken = localStorage.getItem('da_refresh_token')
  if (!refreshToken) throw new Error('No refresh token')
  const { data } = await axios.post('/api/auth/refresh', { refresh_token: refreshToken })
  localStorage.setItem('da_token', data.access_token)
  return data.access_token as string
}

api.interceptors.response.use(
  r => r,
  async err => {
    const cfg = err.config
    const requestUrl = String(cfg?.url ?? '')
    const isAuthRequest = requestUrl.includes('/api/auth/token') || requestUrl.includes('/api/auth/refresh')

    if (err.response?.status === 401 && !isAuthRequest && cfg && !cfg._retried) {
      cfg._retried = true
      try {
        refreshPromise ??= refreshAccessToken().finally(() => { refreshPromise = null })
        const newToken = await refreshPromise
        cfg.headers.Authorization = `Bearer ${newToken}`
        return api(cfg)
      } catch {
        localStorage.removeItem('da_token')
        localStorage.removeItem('da_refresh_token')
        window.dispatchEvent(new Event('da_auth_expired'))
        return Promise.reject(err)
      }
    }

    if (err.response?.status === 401 && !isAuthRequest) {
      localStorage.removeItem('da_token')
      localStorage.removeItem('da_refresh_token')
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
