import { api } from './client'

export interface PayloadType {
  id?: number
  name: string
  manufacturer: string
  model: string
  category: 'sensor' | 'combat' | 'comms' | 'other'
  weight_kg: number
  voltage_v: number
  max_current_a: number
  sensor_type?: string
  resolution?: string
  frame_rate_fps?: number
  has_gimbal: boolean
  payload_function?: string
  effective_range_m?: number
  notes?: string
  is_active?: boolean
}

export const payloadApi = {
  listTypes: () => api.get<PayloadType[]>('/api/master/payload-types'),
  createType: (payload: PayloadType) => api.post<PayloadType>('/api/master/payload-types', payload),
  updateType: (id: number, payload: PayloadType) =>
    api.put<PayloadType>(`/api/master/payload-types/${id}`, payload),
  deleteType: (id: number) => api.delete(`/api/master/payload-types/${id}`),
  assignToDrone: (droneId: number, payloadTypeId: number | null) =>
    api.post(`/api/master/drones/${droneId}/payload`, { payload_type_id: payloadTypeId }),
}
