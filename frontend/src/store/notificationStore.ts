/**
 * Notification store — shared by NotificationDrawer and SystemLog.
 * Populated by:
 *   - Health monitor alerts (low battery, weak link, GPS warn)
 *   - Connection events (drone connected / disconnected)
 *   - Command results (arm/disarm confirmations, failures)
 *   - Mission status changes
 */
import { create } from 'zustand'
import { eventLog } from './eventLogStore'

export type NotifLevel = 'info' | 'success' | 'warning' | 'danger'

export interface Notification {
  id:        string
  level:     NotifLevel
  title:     string
  message:   string
  droneId?:  number
  timestamp: Date
  read:      boolean
}

interface NotificationState {
  notifications: Notification[]
  unreadCount:   number
  add:    (n: Omit<Notification, 'id' | 'timestamp' | 'read'>) => void
  markAllRead: () => void
  clear:  () => void
}

let _seq = 0

export const useNotificationStore = create<NotificationState>((set, get) => ({
  notifications: [],
  unreadCount:   0,

  add: (n) => {
    const entry: Notification = {
      ...n,
      id:        `notif-${++_seq}`,
      timestamp: new Date(),
      read:      false,
    }
    
    // Also log to event store for audit trail
    const eventLevel = n.level === 'danger' ? 'error' : n.level === 'warning' ? 'warning' : n.level === 'success' ? 'success' : 'info'
    eventLog.system(n.title, n.message, eventLevel)
    
    set(s => ({
      notifications: [entry, ...s.notifications].slice(0, 200),
      unreadCount:   s.unreadCount + 1,
    }))
  },

  markAllRead: () =>
    set(s => ({
      notifications: s.notifications.map(n => ({ ...n, read: true })),
      unreadCount:   0,
    })),

  clear: () => set({ notifications: [], unreadCount: 0 }),
}))

/** Convenience helpers imported by other modules */
export const notify = {
  info:    (title: string, message: string, droneId?: number) =>
    useNotificationStore.getState().add({ level: 'info', title, message, droneId }),
  success: (title: string, message: string, droneId?: number) =>
    useNotificationStore.getState().add({ level: 'success', title, message, droneId }),
  warning: (title: string, message: string, droneId?: number) =>
    useNotificationStore.getState().add({ level: 'warning', title, message, droneId }),
  danger:  (title: string, message: string, droneId?: number) =>
    useNotificationStore.getState().add({ level: 'danger', title, message, droneId }),
}