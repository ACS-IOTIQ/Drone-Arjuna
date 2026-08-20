// ═══════════════════════════════════════════
// src/store/telemetryStore.ts
// ═══════════════════════════════════════════
import { create } from 'zustand'
import { makeTelemetryUrl } from '@/api/client'
import { droneControlApi } from '@/api/droneControl'
import { RobustWebSocket } from '@/store/connectionHealthStore'
import { eventLog } from './eventLogStore'
import { notify } from './notificationStore'

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
  battery_consumption_rate_pct_s?: number
  estimated_endurance_s?: number | null

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
  geofence_breach?: boolean
  breach_lat?: number
  breach_lon?: number
  battery_rtl_triggered?: boolean
  battery_rtl_required_pct?: number
  proximity_alert?: boolean
  manual_control_required?: boolean
  proximity_distance_m?: number | null
  proximity_intruder_drone_id?: number | null

  // Simulation metadata
  sim_phase?: string
  mission_id?: number
  sim_progress?: number
  sim_waypoint_idx?: number
  sim_waypoint_count?: number
  distance_to_destination_m?: number | null

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

function numeric(...values: unknown[]): number | undefined {
  for (const value of values) {
    if (value == null || value === '') continue
    const next = Number(value)
    if (Number.isFinite(next)) return next
  }
  return undefined
}

function coordinate(primary: unknown, scaled: unknown, fallback: number): number {
  const direct = numeric(primary)
  if (direct !== undefined) return direct

  const raw = numeric(scaled)
  if (raw === undefined) return fallback

  // MAVLink GLOBAL_POSITION_INT uses degrees * 1e7.
  if (Math.abs(raw) > 180) return raw / 1e7
  return raw
}

function angularRateDps(degreesPerSecond: unknown, ...radiansPerSecond: unknown[]): number | undefined {
  const direct = numeric(degreesPerSecond)
  if (direct !== undefined) return direct
  const radians = numeric(...radiansPerSecond)
  return radians === undefined ? undefined : radians * (180 / Math.PI)
}

function normalizeTelemetryFrame(raw: unknown, prev?: TelemetryFrame): TelemetryFrame | null {
  if (!raw || typeof raw !== 'object') return null
  const data = raw as Record<string, any>
  const base = { ...DEFAULT_FRAME, ...(prev ?? {}) }

  const lat = coordinate(data.lat ?? data.latitude, data.lat_int ?? data.latitude_int, base.lat)
  const lon = coordinate(data.lon ?? data.lng ?? data.longitude, data.lon_int ?? data.longitude_int, base.lon)
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null

  const frame: TelemetryFrame = {
    ...base,
    ...data,
    drone_id: numeric(data.drone_id, data.droneId, base.drone_id),
    call_sign: data.call_sign ?? data.callSign ?? base.call_sign,
    lat,
    lon,
    alt_msl: numeric(data.alt_msl, data.altitude_msl, data.alt, data.altitude, base.alt_msl) ?? base.alt_msl,
    alt_agl: numeric(data.alt_agl, data.relative_alt, data.relative_alt_m, data.altitude_agl, base.alt_agl) ?? base.alt_agl,
    heading: numeric(data.heading, data.hdg, data.yaw_deg, base.heading) ?? base.heading,
    roll_deg: numeric(data.roll_deg, data.roll, base.roll_deg) ?? base.roll_deg,
    pitch_deg: numeric(data.pitch_deg, data.pitch, base.pitch_deg) ?? base.pitch_deg,
    yaw_deg: numeric(data.yaw_deg, data.yaw, data.heading, base.yaw_deg) ?? base.yaw_deg,
    airspeed_ms: numeric(data.airspeed_ms, data.airspeed, base.airspeed_ms) ?? base.airspeed_ms,
    groundspeed_ms: numeric(data.groundspeed_ms, data.ground_speed_ms, data.groundspeed, data.speed_ms, base.groundspeed_ms) ?? base.groundspeed_ms,
    climb_rate_ms: numeric(data.climb_rate_ms, data.climb, data.vertical_speed_ms, base.climb_rate_ms) ?? base.climb_rate_ms,
    throttle_pct: numeric(data.throttle_pct, data.throttle, base.throttle_pct) ?? base.throttle_pct,
    battery_voltage_v: numeric(data.battery_voltage_v, data.voltage_battery_v, base.battery_voltage_v) ?? base.battery_voltage_v,
    battery_remaining_pct: numeric(data.battery_remaining_pct, data.battery_pct, data.battery_remaining, base.battery_remaining_pct) ?? base.battery_remaining_pct,
    battery_current_a: numeric(data.battery_current_a, data.current_battery_a, base.battery_current_a) ?? base.battery_current_a,
    gps_fix_type: data.gps_fix_type ?? data.gps_fix ?? base.gps_fix_type,
    gps_satellites: numeric(data.gps_satellites, data.satellites_visible, data.sats, base.gps_satellites) ?? base.gps_satellites,
    gps_hdop: numeric(data.gps_hdop, data.hdop, base.gps_hdop) ?? base.gps_hdop,
    flight_mode: data.flight_mode ?? data.mode ?? base.flight_mode,
    is_armed: typeof data.is_armed === 'boolean' ? data.is_armed : Boolean(data.armed ?? base.is_armed),
    rssi: numeric(data.rssi, data.rc_rssi, base.rssi) ?? base.rssi,
    cpu_load_pct: numeric(data.cpu_load_pct, data.cpu_load, base.cpu_load_pct) ?? base.cpu_load_pct,
    last_updated: data.last_updated ?? data.timestamp ?? base.last_updated,
    geofence_breach: data.geofence_breach ?? base.geofence_breach,
    breach_lat: numeric(data.breach_lat, base.breach_lat),
    breach_lon: numeric(data.breach_lon, base.breach_lon),
    battery_rtl_triggered: typeof data.battery_rtl_triggered === 'boolean' ? data.battery_rtl_triggered : base.battery_rtl_triggered,
    battery_rtl_required_pct: numeric(data.battery_rtl_required_pct, base.battery_rtl_required_pct),
    proximity_alert: typeof data.proximity_alert === 'boolean' ? data.proximity_alert : base.proximity_alert,
    manual_control_required: typeof data.manual_control_required === 'boolean' ? data.manual_control_required : base.manual_control_required,
    proximity_distance_m: numeric(data.proximity_distance_m, base.proximity_distance_m ?? undefined) ?? null,
    proximity_intruder_drone_id: numeric(data.proximity_intruder_drone_id, base.proximity_intruder_drone_id ?? undefined) ?? null,
    roll_rate_dps: angularRateDps(data.roll_rate_dps, data.rollspeed, data.imu_xgyro) ?? base.roll_rate_dps,
    pitch_rate_dps: angularRateDps(data.pitch_rate_dps, data.pitchspeed, data.imu_ygyro) ?? base.pitch_rate_dps,
    yaw_rate_dps: angularRateDps(data.yaw_rate_dps, data.yawspeed, data.imu_zgyro) ?? base.yaw_rate_dps,
  }

  return frame
}

function telemetryFramesEqual(a: TelemetryFrame, b: TelemetryFrame): boolean {
  const keys: Array<keyof TelemetryFrame> = [
    'drone_id', 'call_sign', 'lat', 'lon', 'alt_msl', 'alt_agl', 'heading',
    'roll_deg', 'pitch_deg', 'yaw_deg', 'airspeed_ms', 'groundspeed_ms',
    'climb_rate_ms', 'throttle_pct', 'battery_voltage_v', 'battery_remaining_pct',
    'battery_current_a', 'gps_fix_type', 'gps_satellites', 'gps_hdop', 'flight_mode',
    'is_armed', 'rssi', 'cpu_load_pct', 'geofence_breach', 'breach_lat', 'breach_lon',
    'battery_rtl_triggered', 'battery_rtl_required_pct',
    'proximity_alert', 'manual_control_required', 'proximity_distance_m',
    'proximity_intruder_drone_id', 'sim_phase', 'mission_id', 'sim_progress', 'sim_waypoint_idx',
    'sim_waypoint_count', 'distance_to_destination_m', 'nav_wp_dist_m', 'nav_alt_err_m', 'nav_xtrack_err_m',
    'current_wp_num', 'last_status_text', 'last_status_severity', 'home_lat', 'home_lon',
    'home_alt', 'terrain_alt_m', 'ekf_ok', 'ekf_vel_ratio', 'ekf_pos_h_ratio',
    'ekf_pos_v_ratio', 'ekf_compass_ratio', 'ekf_terrain_ratio', 'vibe_x', 'vibe_y',
    'vibe_z', 'vibe_clip_0', 'vibe_clip_1', 'vibe_clip_2', 'imu_xacc', 'imu_yacc',
    'imu_zacc', 'imu_xgyro', 'imu_ygyro', 'imu_zgyro', 'roll_rate_dps', 'pitch_rate_dps',
    'yaw_rate_dps', 'vel_n_ms', 'vel_e_ms', 'vel_d_ms', 'rc_rssi', 'rc1', 'rc2',
    'rc3', 'rc4', 'rc5', 'rc6', 'rc7', 'rc8', 'servo1', 'servo2', 'servo3', 'servo4',
    'press_abs_hpa', 'press_diff_hpa', 'temperature_c',
  ]

  return keys.every(key => a[key] === b[key])
}

// WS messages can arrive faster than the UI can usefully render (10 Hz x N drones).
// Coalesce bursts into a single store update per animation frame per drone.
const pendingRaw: Record<number, unknown> = {}
const pendingFrameHandle: Record<number, number> = {}

function mergeFrame(droneId: number, raw: unknown, set: (partial: Partial<TelemetryState> | ((state: TelemetryState) => Partial<TelemetryState>)) => void, get: () => TelemetryState) {
  pendingRaw[droneId] = raw
  if (pendingFrameHandle[droneId] != null) return
  pendingFrameHandle[droneId] = requestAnimationFrame(() => {
    delete pendingFrameHandle[droneId]
    const latestRaw = pendingRaw[droneId]
    delete pendingRaw[droneId]
    applyFrame(droneId, latestRaw, set, get)
  })
}

function applyFrame(droneId: number, raw: unknown, set: (partial: Partial<TelemetryState> | ((state: TelemetryState) => Partial<TelemetryState>)) => void, get: () => TelemetryState) {
  const frame = normalizeTelemetryFrame(raw, get().frames[droneId])
  if (!frame) return

  const prevFrame = get().frames[droneId]
  if (prevFrame && telemetryFramesEqual(frame, prevFrame)) return

  const wasBreach = Boolean(frame.geofence_breach)
  const wasPrevBreach = Boolean(prevFrame?.geofence_breach)
  const batteryRtl = Boolean(frame.battery_rtl_triggered)
  const hadBatteryRtl = Boolean(prevFrame?.battery_rtl_triggered)
  const hasProximityAlert = Boolean(frame.proximity_alert && frame.manual_control_required)
  const hadProximityAlert = Boolean(prevFrame?.proximity_alert && prevFrame?.manual_control_required)

  if (wasBreach && !wasPrevBreach) {
    const title = 'Geofence breach detected'
    const message = `Drone ${droneId} crossed the configured geofence boundary. Returning to safe state.`
    notify.danger(title, message, droneId)
    eventLog.drone(title, message, String(droneId), 'error')
  } else if (!wasBreach && wasPrevBreach) {
    const title = 'Geofence recovered'
    const message = `Drone ${droneId} has returned inside the configured boundary.`
    notify.warning(title, message, droneId)
    eventLog.drone(title, message, String(droneId), 'warning')
  }

  if (batteryRtl && !hadBatteryRtl) {
    const title = 'Battery auto-RTL triggered'
    const message = `Drone ${droneId} does not have enough battery to complete the remaining waypoints — returning to launch automatically.`
    notify.danger(title, message, droneId)
    eventLog.drone(title, message, String(droneId), 'error')
  }

  if (hasProximityAlert && !hadProximityAlert) {
    const intruder = frame.proximity_intruder_drone_id != null ? `Drone ${frame.proximity_intruder_drone_id}` : 'another drone'
    const distance = frame.proximity_distance_m != null ? ` at ${frame.proximity_distance_m.toFixed(1)} m` : ''
    const title = 'Manual control shift required'
    const message = `Drone ${droneId} is within 250 m of ${intruder}${distance}. Shift to manual control immediately.`
    notify.danger(title, message, droneId)
    eventLog.drone(title, message, String(droneId), 'error')
  } else if (!hasProximityAlert && hadProximityAlert) {
    const title = 'Separation restored'
    const message = `Drone ${droneId} is back outside the 250 m manual-control threshold.`
    notify.success(title, message, droneId)
    eventLog.drone(title, message, String(droneId), 'success')
  }

  set(s => {
    const prev = s.history[droneId] ?? []
    const previousPosition = prev.length > 0 ? prev[prev.length - 1] : undefined
    const samePosition = previousPosition &&
      previousPosition.lat === frame.lat &&
      previousPosition.lon === frame.lon &&
      previousPosition.alt_agl === frame.alt_agl
    const next = samePosition ? prev : [...prev.slice(-299), frame]
    if (prev.length === 0) {
      eventLog.telemetry('Telemetry Stream Started', String(droneId), { call_sign: frame.call_sign })
    } else if (next.length > prev.length && next.length % 300 === 0) {
      eventLog.telemetry('Telemetry Update (sampled)', String(droneId), { call_sign: frame.call_sign })
    }
    return {
      frames:  { ...s.frames,  [droneId]: frame },
      history: { ...s.history, [droneId]: next },
    }
  })
}

interface TelemetryState {
  frames:  Record<number, TelemetryFrame>
  sockets: Record<number, RobustWebSocket>
  history: Record<number, TelemetryFrame[]>   // last 300 frames per drone
  subscribe:   (droneId: number) => void
  unsubscribe: (droneId: number) => void
  clearDrone:   (droneId: number) => void
}

export const useTelemetryStore = create<TelemetryState>((set, get) => ({
  frames:  {},
  sockets: {},
  history: {},

  subscribe: (droneId) => {
    if (get().sockets[droneId]) {
      console.log('[Telemetry] already subscribed to drone', droneId)
      droneControlApi.telemetry(droneId)
        .then(({ data }) => mergeFrame(droneId, data, set, get))
        .catch(() => {})
      return
    }

    const url = makeTelemetryUrl(droneId)
    const rws = new RobustWebSocket(url, `telemetry-${droneId}`, () => makeTelemetryUrl(droneId))

    rws.onOpen(() => console.log('[Telemetry] RobustWebSocket OPEN drone', droneId))
    rws.onError((e) => console.error('[Telemetry] RobustWebSocket ERROR drone', droneId, e))

    rws.onMessage((data) => {
      try {
        const frame = JSON.parse(data)
        if (frame?.type === 'pong') return
        mergeFrame(droneId, frame, set, get)
      } catch { /* ignore parse errors */ }
    })

    rws.onClose(() => {
      console.warn('[Telemetry] RobustWebSocket CLOSE drone', droneId)
    })

    rws.connect()

    set(s => ({
      sockets: { ...s.sockets, [droneId]: rws },
      frames:  { ...s.frames,  [droneId]: s.frames[droneId] ?? DEFAULT_FRAME },
    }))

    droneControlApi.telemetry(droneId)
      .then(({ data }) => mergeFrame(droneId, data, set, get))
      .catch(() => {})
  },

  unsubscribe: (droneId) => {
    get().sockets[droneId]?.close()
    set(s => {
      const { [droneId]: _, ...socks } = s.sockets
      return { sockets: socks }
    })
  },

  clearDrone: (droneId) => {
    get().sockets[droneId]?.close()
    set(s => {
      const { [droneId]: _socket, ...sockets } = s.sockets
      const { [droneId]: _frame, ...frames } = s.frames
      const { [droneId]: _history, ...history } = s.history
      return { sockets, frames, history }
    })
  },
}))
