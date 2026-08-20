
// ═══════════════════════════════════════════
// src/store/fleetStore.ts
// ═══════════════════════════════════════════
import { create } from 'zustand'
import { droneControlApi } from '@/api/droneControl'
import { droneMasterApi } from '@/api/droneMaster'
import { useTelemetryStore } from '@/store/telemetryStore'

export interface DroneInstance {
  id: number
  call_sign: string
  drone_type_id: number
  serial_number: string
  mavlink_system_id: number
  status: string
  last_seen: string | null
  created_at: string
  total_flight_hours: number
  home_vessel_id: number | null
  payload_type_id: number | null
}

export interface ConnectionInfo {
  connected: boolean
  transport: string
  hf?: {
    state: 'connected' | 'degraded' | 'lost'
    snr_db: number | null
    silence_s: number
    modem_type: string
  }
}

interface FleetState {
  instances: DroneInstance[]
  connections: Record<number, ConnectionInfo>
  isLoading: boolean
  connectionFetchFailures: number
  fetchInstances: () => Promise<void>
  fetchConnections: () => Promise<void>
}

export const STALE_DRONE_DAYS = 30

export function getDroneLastActivity(drone: DroneInstance): Date | null {
  const value = drone.last_seen ?? drone.created_at
  if (!value) return null
  const timestamp = new Date(value)
  return Number.isNaN(timestamp.getTime()) ? null : timestamp
}

export function isDroneStale(drone: DroneInstance, now = new Date()): boolean {
  const lastActivity = getDroneLastActivity(drone)
  if (!lastActivity) return false
  return now.getTime() - lastActivity.getTime() >= STALE_DRONE_DAYS * 24 * 60 * 60 * 1000
}

/** Operational order used everywhere: connected first, then most recently used. */
export function sortDronesByActivity(
  instances: DroneInstance[],
  connections: Record<number, ConnectionInfo>,
): DroneInstance[] {
  return [...instances].sort((a, b) => {
    const aConnected = connections[a.id]?.connected ? 1 : 0
    const bConnected = connections[b.id]?.connected ? 1 : 0
    if (aConnected !== bConnected) return bConnected - aConnected

    const aActivity = getDroneLastActivity(a)?.getTime() ?? 0
    const bActivity = getDroneLastActivity(b)?.getTime() ?? 0
    if (aActivity !== bActivity) return bActivity - aActivity
    return a.call_sign.localeCompare(b.call_sign)
  })
}

export const useFleetStore = create<FleetState>((set, get) => ({
  instances: [],
  connections: {},
  isLoading: false,
  connectionFetchFailures: 0,

  fetchInstances: async () => {
    set({ isLoading: true })
    try {
      const { data } = await droneMasterApi.listDrones()
      set(state => ({ instances: sortDronesByActivity(data, state.connections) }))
    } finally {
      set({ isLoading: false })
    }
  },

  fetchConnections: async () => {
    try {
      const { data } = await droneControlApi.status()
      const conns: Record<number, ConnectionInfo> = {}
      for (const d of data.drones ?? []) {
        if (d.connected) {
          conns[d.drone_id] = {
            connected: d.connected,
            transport: d.transport ?? 'unknown',
            hf: d.hf,
          }
        }
      }
      const previousConnections = get().connections
      Object.entries(previousConnections).forEach(([id, connection]) => {
        const droneId = Number(id)
        const nextConnection = conns[droneId]
        if (
          connection.connected &&
          connection.transport === 'simulation' &&
          (!nextConnection?.connected || nextConnection.transport !== 'simulation')
        ) {
          useTelemetryStore.getState().clearDrone(droneId)
        }
      })
      set(state => ({
        connections: conns,
        instances: sortDronesByActivity(state.instances, conns),
        connectionFetchFailures: 0,
      }))
    } catch {
      // Transient network hiccups/timeouts (e.g. backend momentarily busy under
      // simulation load) must not wipe a still-live simulation from the UI —
      // only clear state once failures persist long enough to be a real outage.
      const failures = get().connectionFetchFailures + 1
      set({ connectionFetchFailures: failures })
      if (failures < 10) return

      Object.entries(get().connections).forEach(([id, connection]) => {
        if (connection.connected && connection.transport === 'simulation') {
          useTelemetryStore.getState().clearDrone(Number(id))
        }
      })

      set(state => ({
        connections: {},
        instances: sortDronesByActivity(state.instances, {}),
        connectionFetchFailures: failures,
      }))
    }
  },
}))

