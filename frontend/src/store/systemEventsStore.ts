// ═══════════════════════════════════════════
// src/store/systemEventsStore.ts
// Single WebSocket for backend-initiated system notices (e.g. auto-restore
// after detected data loss). Opened once at app start; drives toasts and
// tells other stores to refetch so the UI reflects restored data.
// ═══════════════════════════════════════════
import { notify } from './notificationStore'
import { useFleetStore } from './fleetStore'
import { useMissionStore } from './missionStore'
import { useVesselStore } from './vesselStore'

let socket: WebSocket | null = null

function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return

  const token = localStorage.getItem('da_token') ?? ''
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  socket = new WebSocket(`${proto}//${host}/api/system/events?token=${token}`)

  socket.onmessage = (event) => {
    let data: { type?: string; message?: string } = {}
    try {
      data = JSON.parse(event.data)
    } catch {
      return
    }

    if (data.type === 'DATA_LOSS_DETECTED') {
      notify.warning('Data Loss Detected', data.message ?? 'Restoring from the latest backup...')
    } else if (data.type === 'DATA_RESTORED') {
      notify.success('Data Restored', data.message ?? 'Database restored from backup.')
      useFleetStore.getState().fetchInstances()
      useFleetStore.getState().fetchConnections()
      useMissionStore.getState().fetchMissions()
      useVesselStore.getState().fetchVessels()
    } else if (data.type === 'BACKUP_MISSING') {
      notify.danger('Backup Unavailable', data.message ?? 'No backup dump is available to restore from.')
    }
  }

  socket.onclose = () => {
    setTimeout(connect, 3000)
  }

  socket.onerror = () => {
    socket?.close()
  }
}

export function initSystemEventsStream() {
  connect()
}
