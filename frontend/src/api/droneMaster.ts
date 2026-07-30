// ═══════════════════════════════════════════
// src/api/droneMaster.ts
// ═══════════════════════════════════════════
import { api } from './client'

export const droneMasterApi = {
  listTypes:    ()          => api.get('/api/master/drone-types'),
  createType:   (d: object) => api.post('/api/master/drone-types', d),
  updateType:   (id: number, d: object) => api.put(`/api/master/drone-types/${id}`, d),
  archiveType:  (id: number) => api.delete(`/api/master/drone-types/${id}`),

  listDrones:   ()          => api.get('/api/master/drones'),
  createDrone:  (d: object) => api.post('/api/master/drones', d),
  updateDrone:  (id: number, d: object) => api.put(`/api/master/drones/${id}`, d),
  getDrone:     (id: number) => api.get(`/api/master/drones/${id}`),
  removeDrone:  (id: number) => api.delete(`/api/master/drones/${id}`),
  removeStaleDrone: (id: number) => api.delete(`/api/master/drones/${id}/stale`),
}
