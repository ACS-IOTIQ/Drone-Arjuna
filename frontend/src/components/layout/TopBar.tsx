import { useEffect, useState } from 'react'
import { Bell, UserRound } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import { useNotificationStore } from '@/store/notificationStore'
import { useTelemetryStore } from '@/store/telemetryStore'
import { useTimezoneStore } from '@/store/timezoneStore'
import { droneControlApi } from '@/api/droneControl'
import type { Workspace } from './AppShell'

const LABELS: Record<Workspace, string> = {
  fleet: 'Fleet Ops',
  plan: 'Mission Plan',
  fly: 'Flight Control',
  monitor: 'Telemetry',
  settings: 'Master Data',
}

interface Props {
  workspace: Workspace
  onNotifClick: () => void
}

function Chip({ tone, dot = true, children }: {
  tone: 'ok' | 'warn' | 'danger' | 'blue' | 'teal' | ''
  dot?: boolean
  children: React.ReactNode
}) {
  return (
    <div className={`da-chip ${tone}`}>
      {dot && <span className="da-chip-dot" />}
      {children}
    </div>
  )
}

export function TopBar({ workspace, onNotifClick }: Props) {
  const { user } = useAuthStore()
  const unreadCount = useNotificationStore(s => s.unreadCount)
  const frames = useTelemetryStore(s => s.frames)
  const primary = Object.values(frames)[0] ?? null
  const [time, setTime] = useState(new Date())
  const [connected, setConnected] = useState(0)
  const timezone = useTimezoneStore(s => s.timezone)
  const formatTime = useTimezoneStore(s => s.formatTime)

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    const poll = async () => {
      try {
        const { data } = await droneControlApi.status()
        setConnected(data.drones?.filter((drone: any) => drone.connected).length ?? 0)
      } catch {
        setConnected(0)
      }
    }
    poll()
    const timer = setInterval(poll, 5000)
    return () => clearInterval(timer)
  }, [])

  const linkTone = connected > 0 ? 'ok' : 'danger'
  const linkLabel = connected > 0 ? `${connected} LINK${connected > 1 ? 'S' : ''}` : 'OFFLINE'
  const armedTone = primary?.is_armed ? 'danger' : 'ok'
  const armedLabel = primary?.is_armed ? 'ARMED' : 'SAFE'
  const mode = primary?.flight_mode ?? null
  const modeTone: 'ok' | 'warn' | 'teal' | '' =
    mode === 'AUTO' ? 'ok' : (mode === 'RTL' || mode === 'LAND') ? 'warn' : mode ? 'teal' : ''
  const battery = primary?.battery_remaining_pct ?? -1
  const batteryTone = battery < 0 ? '' : battery <= 15 ? 'danger' : battery <= 25 ? 'warn' : 'ok'
  const satellites = primary?.gps_satellites ?? -1
  const gpsTone: 'ok' | 'warn' | '' = satellites >= 6 ? 'ok' : satellites >= 0 ? 'warn' : ''

  return (
    <header className="da-topbar">
      <div className="da-workspace-title">
        <span className="da-workspace-kicker">Operations</span>
        <span className="da-workspace-name">{LABELS[workspace]}</span>
      </div>

      <div className="da-status-strip">
        <Chip tone={linkTone}>{linkLabel}</Chip>
        {primary && <Chip tone={armedTone}>{armedLabel}</Chip>}
        {mode && <Chip tone={modeTone} dot={false}>{mode}</Chip>}
        {battery >= 0 && <Chip tone={batteryTone as 'ok' | 'warn' | 'danger'}>BAT {battery}%</Chip>}
        {satellites >= 0 && <Chip tone={gpsTone}>{satellites} SAT</Chip>}
      </div>

      <div className="da-clock">
        <span className="mono text-xs font-medium">{formatTime(time)}</span>
        <span className="text-[9px] uppercase">{timezone}</span>
      </div>

      <button
        onClick={onNotifClick}
        className="da-icon-button relative shrink-0"
        aria-label={unreadCount ? `Open notifications, ${unreadCount} unread` : 'Open notifications'}
        title="Notifications"
        style={{ color: unreadCount > 0 ? 'var(--da-warning)' : 'var(--da-muted)' }}>
        <Bell size={17} />
        {unreadCount > 0 && (
          <span className="da-notification-count">{unreadCount > 9 ? '9+' : unreadCount}</span>
        )}
      </button>

      <div className="da-user-summary">
        <span className="da-user-avatar"><UserRound size={14} /></span>
        <span className="min-w-0">
          <span className="block truncate text-xs font-semibold">{(user as any)?.username ?? 'operator'}</span>
          <span className="block text-[9px] uppercase" style={{ color: 'var(--da-muted)' }}>
            {(user as any)?.role ?? 'viewer'}
          </span>
        </span>
      </div>
    </header>
  )
}

export default TopBar
