import { create } from 'zustand'

interface TimezoneState {
  timezone: string
  offset: number
  autoSync: boolean
  setTimezone: (tz: string) => void
  syncToSystemTimezone: () => void
  formatTime: (date: Date) => string
  formatDateTime: (date: Date) => string
  getOffsetString: () => string
}

export const useTimezoneStore = create<TimezoneState>((set, get) => {
  const getSystemTimezone = () => {
    return Intl.DateTimeFormat().resolvedOptions().timeZone
  }

  const getSystemOffset = () => {
    return -(new Date().getTimezoneOffset() / 60)
  }

  return {
    timezone: getSystemTimezone(),
    offset: getSystemOffset(),
    autoSync: true,

    setTimezone: (tz) => {
      set({ timezone: tz, offset: getSystemOffset() })
      localStorage.setItem('da_timezone', tz)
    },

    syncToSystemTimezone: () => {
      const tz = getSystemTimezone()
      const offset = getSystemOffset()
      set({ timezone: tz, offset })
      localStorage.setItem('da_timezone', tz)
    },

    formatTime: (date) => {
      return new Intl.DateTimeFormat('en-US', {
        timeZone: get().timezone,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
      }).format(date)
    },

    formatDateTime: (date) => {
      return new Intl.DateTimeFormat('en-US', {
        timeZone: get().timezone,
        year: 'numeric',
        month: 'short',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
      }).format(date)
    },

    getOffsetString: () => {
      const offset = get().offset
      const hours = Math.floor(Math.abs(offset))
      const minutes = Math.abs((offset % 1) * 60)
      const sign = offset >= 0 ? '+' : '-'
      return `UTC${sign}${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
    },
  }
})

// Initialize from localStorage
const savedTz = localStorage.getItem('da_timezone')
if (savedTz) {
  useTimezoneStore.setState({ timezone: savedTz })
}

// Auto-sync on mount
if (useTimezoneStore.getState().autoSync) {
  useTimezoneStore.getState().syncToSystemTimezone()
}

/**
 * Format helper for use in components
 */
export const formatLocalTime = (date: Date): string => {
  return useTimezoneStore.getState().formatTime(date)
}

export const formatLocalDateTime = (date: Date): string => {
  return useTimezoneStore.getState().formatDateTime(date)
}

export const getTimezoneOffset = (): string => {
  return useTimezoneStore.getState().getOffsetString()
}

export const getCurrentTimezone = (): string => {
  return useTimezoneStore.getState().timezone
}
