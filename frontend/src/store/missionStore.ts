
// ═══════════════════════════════════════════
// src/store/missionStore.ts
// ═══════════════════════════════════════════
import { create } from 'zustand'
import { droneFlightApi, WaypointInput } from '@/api/droneFlight'

export interface Mission {
  id: number
  name: string
  mission_type: string
  status: string
  drone_instance_id: number | null
  waypoints: WaypointInput[]
  created_at: string
}

export interface LoadedMissionMeta {
  name: string
  mission_type: string
  drone_instance_id: number | null
  home_point_type: string
  home_vessel_id: number | null
}

interface MissionState {
  missions: Mission[]
  activeMissionId: number | null
  draftWaypoints: WaypointInput[]
  isLoading: boolean
  fetchMissions: () => Promise<void>
  setActiveMission: (id: number | null) => void
  addWaypoint: (wp: WaypointInput) => void
  removeWaypoint: (seq: number) => void
  clearDraft: () => void
  saveMission: (name: string, type: string, droneId?: number, homePointType?: string, homeVesselId?: number) => Promise<void>
  loadMission: (id: number) => Promise<LoadedMissionMeta>
}

export const useMissionStore = create<MissionState>((set, get) => ({
  missions: [],
  activeMissionId: null,
  draftWaypoints: [],
  isLoading: false,

  fetchMissions: async () => {
    set({ isLoading: true })
    try {
      const { data } = await droneFlightApi.listMissions()
      set({ missions: data })
    } finally {
      set({ isLoading: false })
    }
  },

  setActiveMission: (id) => set({ activeMissionId: id }),

  addWaypoint: (wp) => set(s => ({
    draftWaypoints: [...s.draftWaypoints, wp],
  })),

  removeWaypoint: (seq) => set(s => ({
    draftWaypoints: s.draftWaypoints
      .filter(w => w.sequence !== seq)
      .map((w, i) => ({ ...w, sequence: i + 1 })),
  })),

  clearDraft: () => set({ draftWaypoints: [] }),

  saveMission: async (name, type, droneId, homePointType = 'fixed', homeVesselId) => {
    const { data } = await droneFlightApi.createMission({
      name, mission_type: type,
      drone_instance_id: droneId,
      home_point_type: homePointType,
      home_vessel_id: homePointType === 'dynamic_vessel' ? homeVesselId : undefined,
      waypoints: get().draftWaypoints,
    })
    set(s => ({ missions: [data, ...s.missions] }))
    get().clearDraft()
  },

  loadMission: async (id) => {
    const { data } = await droneFlightApi.getMission(id)
    set({
      draftWaypoints: (data.waypoints ?? []).map((w: WaypointInput, i: number) => ({
        ...w,
        sequence: i + 1,
      })),
    })
    return {
      name:               data.name,
      mission_type:       data.mission_type ?? 'ISR',
      drone_instance_id:  data.drone_instance_id ?? null,
      home_point_type:    data.home_point_type ?? 'fixed',
      home_vessel_id:     data.home_vessel_id ?? null,
    }
  },
}))