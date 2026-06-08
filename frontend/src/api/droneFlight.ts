
// ═══════════════════════════════════════════
// src/api/droneFlight.ts
// ═══════════════════════════════════════════
import { api } from './client'

export interface WaypointInput {
  sequence: number
  latitude: number
  longitude: number
  altitude_m: number
  altitude_ref?: 'AGL' | 'MSL'
  speed_ms?: number
  action?: string
  loiter_time_s?: number
  is_home?: boolean
}

export interface MissionInput {
  name: string
  description?: string
  mission_type?: string
  drone_instance_id?: number
  home_point_type?: string
  home_vessel_id?: number
  waypoints?: WaypointInput[]
  geofence?: object
}

export const droneFlightApi = {
  listMissions:    ()               => api.get('/api/flight/missions'),
  createMission:   (d: MissionInput) => api.post('/api/flight/missions', d),
  getMission:      (id: number)     => api.get(`/api/flight/missions/${id}`),
  getMissionSummary: (id: number)   => api.get(`/api/flight/missions/${id}/summary`),
  updateStatus:    (id: number, status: string) =>
    api.patch(`/api/flight/missions/${id}/status`, { status }),
  deleteMission:   (id: number)     => api.delete(`/api/flight/missions/${id}`),
}
