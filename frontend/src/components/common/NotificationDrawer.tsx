/**
 * NotificationDrawer
 * Slides in from the right when the bell icon in TopBar is clicked.
 * Displays system alerts populated by notificationStore.
 *
 * Also wires into the telemetry store to auto-generate health alerts
 * when battery, RSSI, or GPS thresholds are breached.
 */
import { useEffect, useRef } from 'react'
import { X, Bell, AlertTriangle, CheckCircle, Info, Trash2 } from 'lucide-react'
import { useNotificationStore, NotifLevel, notify } from '@/store/notificationStore'
import { useTelemetryStore } from '@/store/telemetryStore'
import { useFleetStore } from '@/store/fleetStore'
import { useMissionStore, type Mission } from '@/store/missionStore'
import { isPointInsidePolygon, geoJsonToPolygon } from '@/utils/geofence'

interface Props {
  open:    boolean
  onClose: () => void
}

// Thresholds that mirror the backend HealthMonitor
const THRESH = {
  batteryRtl:  15,
  batteryWarn: 25,
  rssiWarn:    50,
  gpsWarn:     5,
}

const LEVEL_ICON: Record<NotifLevel, React.ReactNode> = {
  danger:  <AlertTriangle size={14} style={{ color: '#ef4444', flexShrink: 0 }} />,
  warning: <AlertTriangle size={14} style={{ color: '#f59e0b', flexShrink: 0 }} />,
  success: <CheckCircle   size={14} style={{ color: '#22c55e', flexShrink: 0 }} />,
  info:    <Info          size={14} style={{ color: '#3b82f6', flexShrink: 0 }} />,
}

const LEVEL_BORDER: Record<NotifLevel, string> = {
  danger:  '#dc2626',
  warning: '#d97706',
  success: '#16a34a',
  info:    '#2563eb',
}

// Missions this drone might be flying, best guess first — used to find
// which geofence (if any) should currently apply to its live position.
const STATUS_PRIORITY: Record<string, number> = { executing: 0, approved: 1, planning: 2, completed: 3, aborted: 4 }

function findGeofenceFor(droneId: number, missions: Mission[]) {
  const candidates = missions
    .filter(m => m.drone_instance_id === droneId && m.geofence)
    .sort((a, b) => (STATUS_PRIORITY[a.status] ?? 9) - (STATUS_PRIORITY[b.status] ?? 9) || b.id - a.id)
  return candidates.length ? geoJsonToPolygon(candidates[0].geofence) : []
}

export default function NotificationDrawer({ open, onClose }: Props) {
  const { notifications, unreadCount, markAllRead, clear } = useNotificationStore()
  const frames    = useTelemetryStore(s => s.frames)
  const { instances, connections } = useFleetStore()
  const { missions, fetchMissions } = useMissionStore()

  // Track previous values to fire alerts only on threshold crossing
  const prevRef = useRef<Record<number, Record<string, boolean>>>({})

  useEffect(() => { fetchMissions() }, [])

  // ── Health threshold watcher ───────────────────────────────
  useEffect(() => {
    const connectedIds = instances
      .filter(d => connections[d.id])
      .map(d => d.id)

    for (const id of connectedIds) {
      const frame = frames[id]
      if (!frame) continue
      const prev = prevRef.current[id] ?? {}
      const call = instances.find(d => d.id === id)?.call_sign ?? `Drone ${id}`

      // Battery RTL
      const batt = frame.battery_remaining_pct
      if (batt >= 0 && batt <= THRESH.batteryRtl && !prev.battRtl) {
        notify.danger('Auto-RTL triggered', `${call} battery at ${batt}% — returning to launch`, id)
        prev.battRtl = true
      } else if (batt > THRESH.batteryRtl + 5) {
        prev.battRtl = false
      }

      // Battery warning
      if (batt >= 0 && batt <= THRESH.batteryWarn && !prev.battWarn) {
        notify.warning('Low battery', `${call} battery at ${batt}%`, id)
        prev.battWarn = true
      } else if (batt > THRESH.batteryWarn + 5) {
        prev.battWarn = false
      }

      // RSSI warning
      const rssi = frame.rssi
      if (rssi > 0 && rssi < THRESH.rssiWarn && !prev.rssiWarn) {
        notify.warning('Weak link', `${call} RSSI at ${rssi}`, id)
        prev.rssiWarn = true
      } else if (rssi >= THRESH.rssiWarn + 10) {
        prev.rssiWarn = false
      }

      // GPS warning
      const sats = frame.gps_satellites
      if (sats < THRESH.gpsWarn && !prev.gpsWarn) {
        notify.warning('Low GPS satellites', `${call} only ${sats} satellites visible`, id)
        prev.gpsWarn = true
      } else if (sats >= THRESH.gpsWarn + 2) {
        prev.gpsWarn = false
      }

      // Geofence breach — only checked once the drone has a real fix
      const hasPosition = frame.lat !== 0 || frame.lon !== 0
      if (hasPosition) {
        const polygon = findGeofenceFor(id, missions)
        const outside = polygon.length >= 3 && !isPointInsidePolygon({ lat: frame.lat, lng: frame.lon }, polygon)
        if (outside && !prev.geofenceOut) {
          notify.danger('Geofence breach', `${call} has left its assigned geofence`, id)
          prev.geofenceOut = true
        } else if (!outside && prev.geofenceOut) {
          notify.success('Back inside geofence', `${call} has returned within its assigned zone`, id)
          prev.geofenceOut = false
        }
      }

      prevRef.current[id] = prev
    }
  }, [frames, instances, connections, missions])

  // Mark read when drawer opens
  useEffect(() => {
    if (open) markAllRead()
  }, [open, markAllRead])

  useEffect(() => {
    if (!open) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [open, onClose])

  return (
    <>
      {open && (
        <div
          className="da-notification-backdrop fixed inset-0"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <div
        className={`da-notification-panel fixed flex flex-col ${open ? 'is-open' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
        aria-label="Notifications">
        <div className="da-notification-header">
          <div className="flex min-w-0 items-center gap-3">
            <span className="da-notification-header-icon"><Bell size={17} /></span>
            <div className="min-w-0">
              <span className="block text-sm font-semibold">Notifications</span>
              <span className="block text-[10px]" style={{ color: 'var(--da-muted)' }}>
                System health and mission activity
              </span>
            </div>
            {unreadCount > 0 && (
              <span className="da-badge bg-red-50 text-red-700">
                {unreadCount}
              </span>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {notifications.length > 0 && (
              <button
                onClick={clear}
                className="da-icon-button"
                title="Clear all notifications"
                aria-label="Clear all notifications">
                <Trash2 size={15} />
              </button>
            )}
            <button onClick={onClose} className="da-icon-button" title="Close notifications" aria-label="Close notifications">
              <X size={17} />
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          {notifications.length === 0 ? (
            <div className="flex h-52 flex-col items-center justify-center gap-3 text-center">
              <span className="da-empty-icon"><Bell size={21} /></span>
              <div>
                <p className="text-sm font-semibold">All clear</p>
                <p className="mt-1 text-xs" style={{ color: 'var(--da-muted)' }}>New operational alerts will appear here.</p>
              </div>
            </div>
          ) : (
            notifications.map(n => (
              <div
                key={n.id}
                className={`da-notification-item ${n.read ? '' : 'is-unread'}`}
                style={{ borderLeftColor: LEVEL_BORDER[n.level] }}>
                <div className="mt-0.5 shrink-0">{LEVEL_ICON[n.level]}</div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-xs font-semibold" style={{ color: 'var(--da-text)' }}>{n.title}</p>
                    <p className="mono shrink-0 text-[9px]" style={{ color: 'var(--da-muted)' }}>
                      {n.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </p>
                  </div>
                  <p className="mt-1 break-words text-xs leading-relaxed" style={{ color: 'var(--da-muted)' }}>
                    {n.message}
                  </p>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </>
  )
}
