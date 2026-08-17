// ═══════════════════════════════════════════
// src/store/missionStore.ts
// ═══════════════════════════════════════════
import { create } from "zustand";
import { droneFlightApi, WaypointInput } from "@/api/droneFlight";

export interface GeoPoint {
  lat: number;
  lng: number;
}

export interface Mission {
  id: number;
  name: string;
  mission_type: string;
  status: string;
  drone_instance_id: number | null;
  waypoints: WaypointInput[];
  geofence?: object | null;
  created_at: string;
}

export interface LoadedMissionMeta {
  name: string;
  mission_type: string;
  drone_instance_id: number | null;
  home_point_type: string;
  home_vessel_id: number | null;
}

interface MissionState {
  missions: Mission[];
  activeMissionId: number | null;
  draftWaypoints: WaypointInput[];
  geofence: GeoPoint[];
  isLoading: boolean;
  governmentZonesEnabled: boolean;
  setGovernmentZonesEnabled: (enabled: boolean) => void;
  fetchMissions: () => Promise<void>;
  setActiveMission: (id: number | null) => void;
  addWaypoint: (wp: WaypointInput) => void;
  removeWaypoint: (seq: number) => void;
  setHomeWaypoint: (seq: number) => void;
  clearHomeWaypoint: (seq?: number) => void;
  setGeofence: (points: GeoPoint[]) => void;
  updateGeofencePoint: (idx: number, point: GeoPoint) => void;
  clearGeofence: () => void;
  clearDraft: () => void;
  saveMission: (
    name: string,
    type: string,
    droneId?: number,
    homePointType?: string,
    homeVesselId?: number,
  ) => Promise<void>;
  updateMission: (
    id: number,
    name: string,
    type: string,
    droneId?: number,
    homePointType?: string,
    homeVesselId?: number,
  ) => Promise<void>;
  loadMission: (id: number) => Promise<LoadedMissionMeta>;
  deleteMission: (id: number) => Promise<void>;
  updateMissionStatus: (
    id: number,
    status: "planning" | "approved" | "executing" | "completed" | "aborted",
  ) => Promise<void>;
}

function geofenceToGeoJson(points: GeoPoint[]) {
  if (points.length < 3) return undefined;
  const ring = points.map((p) => [p.lng, p.lat]);
  ring.push([points[0].lng, points[0].lat]);
  return { type: "Polygon", coordinates: [ring] };
}

function geoJsonToGeofence(geofence: any): GeoPoint[] {
  const ring = geofence?.coordinates?.[0];
  if (!Array.isArray(ring)) return [];
  return ring
    .slice(0, ring.length > 1 ? -1 : ring.length)
    .map((p: number[]) => ({ lng: Number(p[0]), lat: Number(p[1]) }))
    .filter((p: GeoPoint) => Number.isFinite(p.lat) && Number.isFinite(p.lng));
}

export const useMissionStore = create<MissionState>((set, get) => ({
  missions: [],
  activeMissionId: null,
  draftWaypoints: [],
  geofence: [],
  isLoading: false,
  governmentZonesEnabled: true,

  setGovernmentZonesEnabled: (enabled) =>
    set({ governmentZonesEnabled: enabled }),

  fetchMissions: async () => {
    set({ isLoading: true });
    try {
      const { data } = await droneFlightApi.listMissions();
      set({ missions: data });
    } finally {
      set({ isLoading: false });
    }
  },

  setActiveMission: (id) => set({ activeMissionId: id }),

  addWaypoint: (wp) =>
    set((s) => ({
      draftWaypoints: [...s.draftWaypoints, wp],
    })),

  removeWaypoint: (seq) =>
    set((s) => {
      const removedHome = s.draftWaypoints.some(
        (w) => w.sequence === seq && w.is_home,
      );
      return {
        draftWaypoints: s.draftWaypoints
          .filter((w) => w.sequence !== seq)
          .map((w, i) => ({
            ...w,
            sequence: i + 1,
            is_home: removedHome ? false : w.is_home,
          })),
      };
    }),

  setHomeWaypoint: (seq) =>
    set((s) => ({
      draftWaypoints: s.draftWaypoints.map((w) => ({
        ...w,
        is_home: w.sequence === seq,
      })),
    })),

  clearHomeWaypoint: (seq) =>
    set((s) => ({
      draftWaypoints: s.draftWaypoints.map((w) => ({
        ...w,
        is_home: seq != null ? (w.sequence === seq ? false : w.is_home) : false,
      })),
    })),

  setGeofence: (points) => set({ geofence: points }),

  updateGeofencePoint: (idx, point) =>
    set((s) => ({
      geofence: s.geofence.map((p, i) => (i === idx ? point : p)),
    })),

  clearGeofence: () => set({ geofence: [] }),

  clearDraft: () =>
    set({ draftWaypoints: [], geofence: [], activeMissionId: null }),

  saveMission: async (
    name,
    type,
    droneId,
    homePointType = "fixed",
    homeVesselId,
  ) => {
    const { data } = await droneFlightApi.createMission({
      name,
      mission_type: type,
      drone_instance_id: droneId,
      home_point_type: homePointType,
      home_vessel_id:
        homePointType === "dynamic_vessel" ? homeVesselId : undefined,
      waypoints: get().draftWaypoints,
      geofence: geofenceToGeoJson(get().geofence),
      enforce_airspace: get().governmentZonesEnabled,
    });
    set((s) => ({ missions: [data, ...s.missions], activeMissionId: data.id }));
  },

  updateMission: async (
    id,
    name,
    type,
    droneId,
    homePointType = "fixed",
    homeVesselId,
  ) => {
    const { data } = await droneFlightApi.updateMission(id, {
      name,
      mission_type: type,
      drone_instance_id: droneId,
      home_point_type: homePointType,
      home_vessel_id:
        homePointType === "dynamic_vessel" ? homeVesselId : undefined,
      waypoints: get().draftWaypoints,
      geofence: geofenceToGeoJson(get().geofence),
      enforce_airspace: get().governmentZonesEnabled,
    });
    set((s) => ({
      missions: s.missions.map((m) => (m.id === id ? { ...m, ...data } : m)),
    }));
  },

  loadMission: async (id) => {
    const { data } = await droneFlightApi.getMission(id);
    set({
      activeMissionId: id,
      draftWaypoints: (data.waypoints ?? []).map(
        (w: WaypointInput, i: number) => ({
          ...w,
          sequence: i + 1,
        }),
      ),
      geofence: geoJsonToGeofence(data.geofence),
    });
    return {
      name: data.name,
      mission_type: data.mission_type ?? "ISR",
      drone_instance_id: data.drone_instance_id ?? null,
      home_point_type: data.home_point_type ?? "fixed",
      home_vessel_id: data.home_vessel_id ?? null,
    };
  },

  deleteMission: async (id) => {
    await droneFlightApi.deleteMission(id);
    set((s) => {
      const deletingActiveMission = s.activeMissionId === id;
      return {
        missions: s.missions.filter((mission) => mission.id !== id),
        ...(deletingActiveMission
          ? { activeMissionId: null, draftWaypoints: [], geofence: [] }
          : {}),
      };
    });
  },

  updateMissionStatus: async (id, status) => {
    await droneFlightApi.updateStatus(id, status);
    set((s) => ({
      missions: s.missions.map((m) => (m.id === id ? { ...m, status } : m)),
    }));
  },
}));
