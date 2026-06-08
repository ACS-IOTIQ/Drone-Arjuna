import { create } from 'zustand'
import { vesselApi } from '../api/vessel'

export interface NavalVessel {
  id: number
  vessel_id: string
  name: string
  vessel_type: string
  hull_number: string | null
  latitude: number | null
  longitude: number | null
  heading_deg: number | null
  speed_kts: number | null
  position_updated_at: string | null
  sea_state: number
  deck_status: 'clear' | 'occupied' | 'restricted'
  landing_spots: number
  hf_modem_type: string | null
  hf_frequency_mhz: number | null
  hf_link_encrypted: boolean
  is_active: boolean
  notes: string | null
}

interface VesselState {
  vessels: NavalVessel[]
  loading: boolean
  error: string | null
  fetchVessels: () => Promise<void>
  updatePositionLocal: (id: number, lat: number, lon: number, heading?: number, speed?: number) => void
}

export const useVesselStore = create<VesselState>((set) => ({
  vessels: [],
  loading: false,
  error: null,

  fetchVessels: async () => {
    set({ loading: true, error: null })
    try {
      const vessels = await vesselApi.list()
      set({ vessels, loading: false })
    } catch (err: any) {
      set({ loading: false, error: err?.message ?? 'Failed to fetch vessels' })
    }
  },

  updatePositionLocal: (id, lat, lon, heading, speed) => {
    set((state) => ({
      vessels: state.vessels.map((v) =>
        v.id === id
          ? {
              ...v,
              latitude: lat,
              longitude: lon,
              heading_deg: heading ?? v.heading_deg,
              speed_kts: speed ?? v.speed_kts,
              position_updated_at: new Date().toISOString(),
            }
          : v
      ),
    }))
  },
}))
