import { create } from 'zustand'

export type EventCategory = 'auth' | 'drone' | 'mission' | 'command' | 'system' | 'connection' | 'telemetry'
export type EventLevel = 'info' | 'success' | 'warning' | 'error'

export interface SystemEvent {
  id: string
  timestamp: Date
  category: EventCategory
  level: EventLevel
  title: string
  description: string
  details?: Record<string, any>
  userId?: string
  droneId?: string
  missionId?: string
}

interface EventLogState {
  events: SystemEvent[]
  addEvent: (event: Omit<SystemEvent, 'id' | 'timestamp'>) => void
  getEventsByCategory: (category: EventCategory) => SystemEvent[]
  getEventsByDrone: (droneId: string) => SystemEvent[]
  getRecentEvents: (limit: number) => SystemEvent[]
  clearOldEvents: (daysOld: number) => void
  exportLogs: (format: 'json' | 'csv') => string
}

let _seq = 0

export const useEventLogStore = create<EventLogState>((set, get) => ({
  events: [],

  addEvent: (event) => {
    const entry: SystemEvent = {
      ...event,
      id: `event-${++_seq}-${Date.now()}`,
      timestamp: new Date(),
    }
    set(s => ({
      events: [entry, ...s.events].slice(0, 5000), // Keep last 5000 events
    }))
  },

  getEventsByCategory: (category) => {
    return get().events.filter(e => e.category === category)
  },

  getEventsByDrone: (droneId) => {
    return get().events.filter(e => e.droneId === droneId)
  },

  getRecentEvents: (limit) => {
    return get().events.slice(0, limit)
  },

  clearOldEvents: (daysOld) => {
    const cutoffDate = new Date()
    cutoffDate.setDate(cutoffDate.getDate() - daysOld)
    set(s => ({
      events: s.events.filter(e => e.timestamp > cutoffDate),
    }))
  },

  exportLogs: (format) => {
    const events = get().events
    if (format === 'json') {
      return JSON.stringify(events, null, 2)
    } else if (format === 'csv') {
      const headers = ['Timestamp', 'Category', 'Level', 'Title', 'Description', 'User ID', 'Drone ID']
      const rows = events.map(e => [
        e.timestamp.toISOString(),
        e.category,
        e.level,
        e.title,
        e.description,
        e.userId || '',
        e.droneId || '',
      ])
      const csv = [headers, ...rows].map(row => row.map(cell => `"${cell}"`).join(',')).join('\n')
      return csv
    }
    return ''
  },
}))

// ─────────────────────────────────────────────────
// Helper Functions — Use These Throughout Frontend
// ─────────────────────────────────────────────────

export const eventLog = {
  auth: (title: string, description: string, userId?: string) => {
    useEventLogStore.getState().addEvent({
      category: 'auth',
      level: 'info',
      title,
      description,
      userId,
    })
  },

  authSuccess: (title: string, userId: string) => {
    useEventLogStore.getState().addEvent({
      category: 'auth',
      level: 'success',
      title,
      description: `User ${userId} successfully ${title.toLowerCase()}`,
      userId,
    })
  },

  authError: (title: string, description: string, userId?: string) => {
    useEventLogStore.getState().addEvent({
      category: 'auth',
      level: 'error',
      title,
      description,
      userId,
    })
  },

  drone: (title: string, description: string, droneId?: string, level: EventLevel = 'info') => {
    useEventLogStore.getState().addEvent({
      category: 'drone',
      level,
      title,
      description,
      droneId,
    })
  },

  command: (title: string, description: string, droneId: string, details?: Record<string, any>) => {
    useEventLogStore.getState().addEvent({
      category: 'command',
      level: 'info',
      title,
      description,
      droneId,
      details,
    })
  },

  mission: (title: string, description: string, missionId?: string, level: EventLevel = 'info') => {
    useEventLogStore.getState().addEvent({
      category: 'mission',
      level,
      title,
      description,
      missionId,
    })
  },

  connection: (title: string, description: string, droneId?: string, level: EventLevel = 'info') => {
    useEventLogStore.getState().addEvent({
      category: 'connection',
      level,
      title,
      description,
      droneId,
    })
  },

  telemetry: (title: string, droneId: string, details?: Record<string, any>) => {
    useEventLogStore.getState().addEvent({
      category: 'telemetry',
      level: 'info',
      title,
      description: `Telemetry update from drone ${droneId}`,
      droneId,
      details,
    })
  },

  system: (title: string, description: string, level: EventLevel = 'info') => {
    useEventLogStore.getState().addEvent({
      category: 'system',
      level,
      title,
      description,
    })
  },
}
