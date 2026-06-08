/**
 * NotificationDrawer
 * Slides in from the right when the bell icon in TopBar is clicked.
 * Displays system alerts populated by notificationStore.
 *
 * Also wires into the telemetry store to auto-generate health alerts
 * when battery, RSSI, or GPS thresholds are breached.
 */
import { useEffect, useRef } from 'react'
import { X, Bell, BatteryLow, Wifi, Satellite, AlertTriangle, CheckCircle, Info } from 'lucide-react'
import { useNotificationStore, NotifLevel, notify } from '@/store/notificationStore'
import { useTelemetryStore } from '@/store/telemetryStore'
import { useFleetStore } from '@/store/fleetStore'

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
  danger:  'rgba(239,68,68,0.2)',
  warning: 'rgba(245,158,11,0.2)',
  success: 'rgba(34,197,94,0.15)',
  info:    'rgba(59,130,246,0.15)',
}

export default function NotificationDrawer({ open, onClose }: Props) {
  const { notifications, unreadCount, markAllRead, clear } = useNotificationStore()
  const frames    = useTelemetryStore(s => s.frames)
  const { instances, connections } = useFleetStore()

  // Track previous values to fire alerts only on threshold crossing
  const prevRef = useRef<Record<number, Record<string, boolean>>>({})

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

      prevRef.current[id] = prev
    }
  }, [frames, instances, connections])

  // Mark read when drawer opens
  useEffect(() => {
    if (open) markAllRead()
  }, [open])

  return (
    <>
      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-40"
          style={{ background: 'rgba(0,0,0,0.3)' }}
          onClick={onClose}
        />
      )}

      {/* Drawer */}
      <div
        className="fixed top-0 right-0 z-50 h-screen flex flex-col"
        style={{
          width:      320,
          background: 'var(--da-surface)',
          borderLeft: '1px solid var(--da-border)',
          transform:  open ? 'translateX(0)' : 'translateX(100%)',
          transition: 'transform 0.22s ease',
        }}>

        {/* Header */}
        <div
          className="flex items-center justify-between px-4 shrink-0"
          style={{ height: 52, borderBottom: '1px solid var(--da-border)' }}>
          <div className="flex items-center gap-2">
            <Bell size={15} style={{ color: '#6b7280' }} />
            <span className="text-sm font-semibold">Notifications</span>
            {unreadCount > 0 && (
              <span
                className="text-xs font-bold px-1.5 py-0.5 rounded-full"
                style={{ background: '#ef4444', color: 'white', fontSize: 10 }}>
                {unreadCount}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {notifications.length > 0 && (
              <button
                onClick={clear}
                className="text-xs"
                style={{ color: '#6b7280' }}>
                Clear all
              </button>
            )}
            <button onClick={onClose}>
              <X size={16} style={{ color: '#6b7280' }} />
            </button>
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto">
          {notifications.length === 0 ? (
            <div
              className="flex flex-col items-center justify-center h-48 gap-2"
              style={{ color: '#374151' }}>
              <Bell size={28} style={{ opacity: 0.3 }} />
              <p className="text-xs">No notifications</p>
            </div>
          ) : (
            notifications.map(n => (
              <div
                key={n.id}
                className="px-4 py-3 flex gap-3"
                style={{
                  borderBottom: `1px solid var(--da-border)`,
                  borderLeft:   `3px solid ${LEVEL_BORDER[n.level]}`,
                  background:   n.read ? 'transparent' : 'rgba(255,255,255,0.02)',
                }}>
                <div className="mt-0.5">{LEVEL_ICON[n.level]}</div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-semibold" style={{ color: '#e2e8f0' }}>
                    {n.title}
                  </p>
                  <p className="text-xs mt-0.5" style={{ color: '#6b7280' }}>
                    {n.message}
                  </p>
                  <p className="text-xs mt-1 mono" style={{ color: '#374151' }}>
                    {n.timestamp.toLocaleTimeString()}
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