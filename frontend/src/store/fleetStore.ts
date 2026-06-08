
// ═══════════════════════════════════════════
// src/store/fleetStore.ts
// ═══════════════════════════════════════════
import { create } from 'zustand'
import { droneControlApi } from '@/api/droneControl'
import { droneMasterApi } from '@/api/droneMaster'

export interface DroneInstance {
  id: number
  call_sign: string
  drone_type_id: number
  serial_number: string
  status: string
  last_seen: string | null
  total_flight_hours: number
  home_vessel_id: number | null
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
  fetchInstances: () => Promise<void>
  fetchConnections: () => Promise<void>
}

export const useFleetStore = create<FleetState>((set) => ({
  instances: [],
  connections: {},
  isLoading: false,

  fetchInstances: async () => {
    set({ isLoading: true })
    try {
      const { data } = await droneMasterApi.listDrones()
      set({ instances: data })
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
      set({ connections: conns })
    } catch { /* offline graceful */ }
  },
}))

