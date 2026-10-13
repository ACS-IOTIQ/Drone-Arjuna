// ═══════════════════════════════════════════
// src/api/client.ts  — Axios base instance
// ═══════════════════════════════════════════
import axios from 'axios'

// Use relative URLs so all requests go through the Vite proxy.
// Vite proxy maps /api → http://backend:8000 and /ws → ws://backend:8000
// This avoids CORS entirely since browser and API appear on the same origin.
// Sessions live in HttpOnly cookies set by the backend, so no token is ever
// readable from JavaScript (an XSS bug cannot steal it). State-changing
// requests carry a custom header the backend requires for cookie-authenticated
// calls, which a cross-site request cannot add (CSRF defence).
export const api = axios.create({
  baseURL: '',
  timeout: 30000,
  withCredentials: true,
  headers: { 'X-Requested-With': 'DroneArjuna' },
})

// On 401 -> try a silent refresh (refresh cookie) and retry the original
// request once. Only log the user out if the refresh itself fails or the
// request was already retried.
let refreshPromise: Promise<void> | null = null

async function refreshSession(): Promise<void> {
  await axios.post('/api/auth/refresh', {}, {
    withCredentials: true,
    headers: { 'X-Requested-With': 'DroneArjuna' },
  })
}

api.interceptors.response.use(
  r => r,
  async err => {
    const cfg = err.config
    const requestUrl = String(cfg?.url ?? '')
    const isAuthRequest = requestUrl.includes('/api/auth/token') || requestUrl.includes('/api/auth/refresh')
      || requestUrl.includes('/api/auth/logout')

    if (err.response?.status === 401 && !isAuthRequest && cfg && !cfg._retried) {
      cfg._retried = true
      try {
        refreshPromise ??= refreshSession().finally(() => { refreshPromise = null })
        await refreshPromise
        return api(cfg)
      } catch {
        window.dispatchEvent(new Event('da_auth_expired'))
        return Promise.reject(err)
      }
    }

    if (err.response?.status === 401 && !isAuthRequest) {
      window.dispatchEvent(new Event('da_auth_expired'))
    }
    return Promise.reject(err)
  }
)

// WebSockets can't send an Authorization header, so we exchange the access
// token for a single-use 30-second ticket over REST and put only that in the
// URL — the long-lived JWT never lands in server, proxy or history logs.
export async function fetchWsTicket(): Promise<string> {
  const { data } = await api.post('/api/auth/ws-ticket')
  return data.ticket as string
}

export async function makeTelemetryUrl(droneId: number): Promise<string> {
  const ticket = encodeURIComponent(await fetchWsTicket())
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host  = window.location.host
  // Route through the /api proxy (ws: true) — backend endpoint is /api/drone-control/stream/{id}
  return `${proto}//${host}/api/drone-control/stream/${droneId}?ticket=${ticket}`
}

export async function makeTelemetryWS(droneId: number): Promise<WebSocket> {
  return new WebSocket(await makeTelemetryUrl(droneId))
}

export async function makeSystemEventsUrl(): Promise<string> {
  const ticket = encodeURIComponent(await fetchWsTicket())
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/api/system/events?ticket=${ticket}`
}

// Payload camera — OpenCV-backed stream. `source` is a bare webcam index
// ("0", "1", ...) or an IP/RTSP/HTTP stream URL/address.
//
// Routed through /camera-api (not /api) — the Vite proxy sends this to the
// natively-run backend (backend/run_native.ps1) instead of the Dockerized
// one, since Docker Desktop on Windows can't pass a host webcam into a
// container. IP/RTSP camera sources work through either backend; only
// webcam-index sources ("0", "1", ...) require the native one.
export async function makeCameraStreamWS(source: string): Promise<WebSocket> {
  const ticket = encodeURIComponent(await fetchWsTicket())
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host  = window.location.host
  const url = `${proto}//${host}/camera-api/drone-control/camera-stream?source=${encodeURIComponent(source)}&ticket=${ticket}`
  const ws = new WebSocket(url)
  ws.binaryType = 'arraybuffer'
  return ws
}
