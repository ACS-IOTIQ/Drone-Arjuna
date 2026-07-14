
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

export interface FleetTarget {
  id: string
  lat: number
  lon: number
}

export interface FleetAssignInput {
  drone_instance_ids?: number[]
  targets: FleetTarget[]
  qubit_budget?: number
  use_quantum?: boolean
}

export interface FleetAssignment {
  drone_instance_id: number
  call_sign: string | null
  target_id: string
  target_lat: number
  target_lon: number
  distance_m: number
}

export interface FleetAssignResult {
  solver: string
  num_subproblems: number
  total_distance_m: number
  all_feasible: boolean
  assignments: FleetAssignment[]
}

export const droneFlightApi = {
  listMissions:    ()               => api.get('/api/flight/missions'),
  createMission:   (d: MissionInput) => api.post('/api/flight/missions', d),
  getMission:      (id: number)     => api.get(`/api/flight/missions/${id}`),
  getMissionSummary: (id: number)   => api.get(`/api/flight/missions/${id}/summary`),
  updateStatus:    (id: number, status: string) =>
    api.patch(`/api/flight/missions/${id}/status`, { status }),
  deleteMission:   (id: number)     => api.delete(`/api/flight/missions/${id}`),
  assignFleet:     (d: FleetAssignInput) =>
    api.post<FleetAssignResult>('/api/flight/assign-fleet', d),
}
