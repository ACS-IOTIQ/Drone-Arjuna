// ═══════════════════════════════════════════
// src/api/droneControl.ts
// ═══════════════════════════════════════════
import { api } from './client'

export interface ConnectPayload {
  drone_instance_id: number
  transport: 'udp' | 'tcp' | 'serial' | 'hf_serial' | 'hf_tcp'
  host?: string
  port?: number
  serial_port?: string
  baud_rate?: number
  hf_modem_type?: string
}

export interface CommandPayload {
  drone_id: number
  command:
    | 'arm' | 'disarm' | 'set_mode'
    | 'rtl' | 'land' | 'takeoff'
    | 'emergency_stop'
    | 'velocity'       // guided velocity command: params { vx, vy, vz }
    | 'goto'           // guided goto: params { lat, lon, alt }
  params?: Record<string, unknown>
}

export interface SimStartPayload {
  mission_id: number
  drone_instance_id?: number
  speed_multiplier?: number
}

export interface PortInfo {
  port:    string          // e.g. "/dev/ttyUSB0" or "udp:0.0.0.0:14550"
  type:    'serial' | 'usb' | 'udp' | 'tcp'
  desc:    string
  baud?:   number
  source?: 'windows_bridge' | 'container' | 'network'
  com?:    string          // Windows COM port name, e.g. "COM4"
  ready?:  boolean         // true when com_bridge has this port open right now
}

export interface PortsResponse {
  bridge_connected:   boolean
  bridge_active_port: string | null
  ports:              PortInfo[]
}

export interface AutoConnectPayload {
  drone_instance_id: number
}

export const droneControlApi = {
  // ── Connection management ───────────────────────────────────
  status:      ()                          => api.get('/api/drone-control/status'),
  connect:     (p: ConnectPayload)         => api.post('/api/drone-control/connect', p),
  disconnect:  (id: number)               => api.post(`/api/drone-control/disconnect/${id}`),

  // ── Flight commands ─────────────────────────────────────────
  command:     (p: CommandPayload)         => api.post('/api/drone-control/command', p),
  telemetry:   (id: number)               => api.get(`/api/drone-control/telemetry/${id}`),

  /**
   * Send a NED velocity command for manual joystick / WASD control.
   * The backend should forward this as MAVLink SET_POSITION_TARGET_LOCAL_NED in velocity mode.
   */
  velocity: (droneId: number, vx: number, vy: number, vz: number) =>
    api.post('/api/drone-control/command', {
      drone_id: droneId,
      command: 'velocity',
      params: { vx, vy, vz },
    } satisfies CommandPayload),

  // ── Port discovery ──────────────────────────────────────────
  /**
   * Returns available serial/UDP/TCP ports the backend can reach.
   * Response: PortsResponse  { bridge_connected, bridge_active_port, ports[] }
   */
  ports: () => api.get<PortsResponse>('/api/drone-control/ports'),

  /**
   * Starts an auto-connect scan on the backend.
   * The backend probes common SITL ports (UDP 14550/14551/14552, TCP 5760/5762)
   * and available serial ports, and connects automatically on first success.
   */
  autoconnect: (p: AutoConnectPayload) =>
    api.post('/api/drone-control/autoconnect', p),

  // ── Geofence ───────────────────────────────────────────────
  getGeofence:   (id: number)           => api.get(`/api/drone-control/drones/${id}/geofence`),

  // ── Simulation ──────────────────────────────────────────────
  simulateStart:  (p: SimStartPayload)  => api.post('/api/drone-control/simulate/start', p),
  simulateStop:   ()                    => api.delete('/api/drone-control/simulate/stop'),
  simulateStatus: ()                    => api.get('/api/drone-control/simulate/status'),
}
