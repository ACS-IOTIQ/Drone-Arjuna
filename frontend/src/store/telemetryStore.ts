// ═══════════════════════════════════════════
// src/store/telemetryStore.ts
// ═══════════════════════════════════════════
import { create } from 'zustand'
import { makeTelemetryWS } from '@/api/client'

// ── Core flight state (always present) ─────────────────────────
export interface TelemetryFrame {
  drone_id?: number
  call_sign?: string

  // Position & attitude
  lat: number
  lon: number
  alt_msl: number
  alt_agl: number
  heading: number
  roll_deg: number
  pitch_deg: number
  yaw_deg: number

  // Velocity / performance
  airspeed_ms: number
  groundspeed_ms: number
  climb_rate_ms: number
  throttle_pct: number

  // Power
  battery_voltage_v: number
  battery_remaining_pct: number
  battery_current_a: number
  battery_mah_used?: number
  battery_cells?: number
  battery_cell_min_v?: number

  // GPS
  gps_fix_type: string
  gps_satellites: number
  gps_hdop: number
  gps_vdop?: number
  gps_vel_ms?: number

  // Status
  flight_mode: string
  is_armed: boolean
  rssi: number
  cpu_load_pct: number
  last_updated: string | null

  // Simulation metadata
  sim_phase?: string

  // ── Extended telemetry fields (optional — sent when backend has them) ──

  // EKF health
  ekf_ok?: boolean
  ekf_vel_ratio?: number
  ekf_pos_h_ratio?: number
  ekf_pos_v_ratio?: number
  ekf_compass_ratio?: number
  ekf_terrain_ratio?: number

  // Vibration / IMU health
  vibe_x?: number
  vibe_y?: number
  vibe_z?: number
  vibe_clip_0?: number
  vibe_clip_1?: number
  vibe_clip_2?: number

  // Raw IMU
  imu_xacc?: number
  imu_yacc?: number
  imu_zacc?: number
  imu_xgyro?: number
  imu_ygyro?: number
  imu_zgyro?: number
  imu_xmag?: number
  imu_ymag?: number
  imu_zmag?: number

  // Angular rates
  roll_rate_dps?: number
  pitch_rate_dps?: number
  yaw_rate_dps?: number

  // Velocity NED
  vel_n_ms?: number
  vel_e_ms?: number
  vel_d_ms?: number

  // RC channels (PWM 1000-2000)
  rc_rssi?: number
  rc1?: number; rc2?: number; rc3?: number; rc4?: number
  rc5?: number; rc6?: number; rc7?: number; rc8?: number

  // Servo outputs
  servo1?: number; servo2?: number; servo3?: number; servo4?: number

  // Barometer
  press_abs_hpa?: number
  press_diff_hpa?: number
  temperature_c?: number

  // Navigation
  nav_wp_dist_m?: number
  nav_alt_err_m?: number
  nav_xtrack_err_m?: number
  current_wp_num?: number

  // Sensor health flags
  sensor_gyro_ok?: boolean
  sensor_accel_ok?: boolean
  sensor_mag_ok?: boolean
  sensor_baro_ok?: boolean
  sensor_gps_ok?: boolean
  sensor_rc_ok?: boolean

  // Comm link
  drop_rate_comm?: number
  errors_comm?: number

  // Last FCU status text
  last_status_text?: string
  last_status_severity?: string

  // Home point
  home_lat?: number
  home_lon?: number
  home_alt?: number

  // Terrain
  terrain_alt_m?: number
}

const DEFAULT_FRAME: TelemetryFrame = {
  lat: 0, lon: 0, alt_msl: 0, alt_agl: 0, heading: 0,
  roll_deg: 0, pitch_deg: 0, yaw_deg: 0,
  airspeed_ms: 0, groundspeed_ms: 0, climb_rate_ms: 0, throttle_pct: 0,
  battery_voltage_v: 0, battery_remaining_pct: -1, battery_current_a: 0,
  gps_fix_type: 'No GPS', gps_satellites: 0, gps_hdop: 99,
  flight_mode: 'UNKNOWN', is_armed: false, rssi: 0, cpu_load_pct: 0,
  last_updated: null,
}

interface TelemetryState {
  frames:  Record<number, TelemetryFrame>
  sockets: Record<number, WebSocket>
  history: Record<number, TelemetryFrame[]>   // last 300 frames per drone
  subscribe:   (droneId: number) => void
  unsubscribe: (droneId: number) => void
}

export const useTelemetryStore = create<TelemetryState>((set, get) => ({
  frames:  {},
  sockets: {},
  history: {},

  subscribe: (droneId) => {
    if (get().sockets[droneId]) {
      console.log('[Telemetry] already subscribed to drone', droneId)
      return
    }
    const ws = makeTelemetryWS(droneId)
    console.log('[Telemetry] WebSocket opening:', ws.url)
    ws.onopen  = () => console.log('[Telemetry] WebSocket OPEN  drone', droneId)
    ws.onerror = (e) => console.error('[Telemetry] WebSocket ERROR drone', droneId, e)

    ws.onmessage = ({ data }) => {
      try {
        const frame: TelemetryFrame = JSON.parse(data)
        if ((frame as any).type === 'pong') return
        set(s => {
          const prev = s.history[droneId] ?? []
          const next = [...prev.slice(-299), frame]
          return {
            frames:  { ...s.frames,  [droneId]: frame },
            history: { ...s.history, [droneId]: next },
          }
        })
      } catch { /* ignore parse errors */ }
    }

    // Keepalive ping every 20s
    const pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ type: 'ping' }))
    }, 20_000)

    ws.onclose = (e) => {
      console.warn('[Telemetry] WebSocket CLOSE drone', droneId, 'code', e.code, e.reason)
      clearInterval(pingInterval)
      set(s => {
        const { [droneId]: _, ...socks } = s.sockets
        return { sockets: socks }
      })
    }

    set(s => ({
      sockets: { ...s.sockets, [droneId]: ws },
      frames:  { ...s.frames,  [droneId]: DEFAULT_FRAME },
    }))
  },

  unsubscribe: (droneId) => {
    get().sockets[droneId]?.close()
    set(s => {
      const { [droneId]: _, ...socks } = s.sockets
      return { sockets: socks }
    })
  },
}))
