import { api } from './client'
import type { NavalVessel } from '../store/vesselStore'

export interface VesselCreatePayload {
  vessel_id: string
  name: string
  vessel_type: string
  hull_number?: string
  sea_state?: number
  deck_status?: string
  landing_spots?: number
  hf_modem_type?: string
  hf_frequency_mhz?: number
  hf_link_encrypted?: boolean
  notes?: string
}

export interface VesselPositionPayload {
  latitude: number
  longitude: number
  heading_deg?: number
  speed_kts?: number
}

export const vesselApi = {
  list: async (): Promise<NavalVessel[]> => {
    const { data } = await api.get('/api/master/vessels')
    return data
  },

  get: async (id: number): Promise<NavalVessel> => {
    const { data } = await api.get(`/api/master/vessels/${id}`)
    return data
  },

  create: async (payload: VesselCreatePayload): Promise<NavalVessel> => {
    const { data } = await api.post('/api/master/vessels', payload)
    return data
  },

  update: async (id: number, payload: Partial<VesselCreatePayload>): Promise<NavalVessel> => {
    const { data } = await api.put(`/api/master/vessels/${id}`, payload)
    return data
  },

  updatePosition: async (id: number, payload: VesselPositionPayload): Promise<NavalVessel> => {
    const { data } = await api.post(`/api/master/vessels/${id}/position`, payload)
    return data
  },

  assignDrone: async (vesselId: number, droneId: number) => {
    const { data } = await api.post(`/api/master/vessels/${vesselId}/assign-drone/${droneId}`)
    return data
  },

  unassignDrone: async (vesselId: number, droneId: number) => {
    const { data } = await api.post(`/api/master/vessels/${vesselId}/unassign-drone/${droneId}`)
    return data
  },

  archive: async (id: number): Promise<void> => {
    await api.delete(`/api/master/vessels/${id}`)
  },
}
