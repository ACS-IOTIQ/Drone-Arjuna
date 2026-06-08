// ═══════════════════════════════════════════════════════════════
// src/components/layout/TopBar.tsx — status chip bar
// ═══════════════════════════════════════════════════════════════
import { useEffect, useState } from 'react'
import { Bell } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import { useNotificationStore } from '@/store/notificationStore'
import { useTelemetryStore } from '@/store/telemetryStore'
import { droneControlApi } from '@/api/droneControl'
import type { Workspace } from './AppShell'

const LABELS: Record<Workspace, string> = {
  fleet:    'Fleet Overview',
  plan:     'Mission Planning',
  fly:      'Live Operations',
  monitor:  'Telemetry Monitor',
  settings: 'Settings & Master Data',
}

interface Props {
  workspace:    Workspace
  onNotifClick: () => void
}

// ── tiny chip primitives ───────────────────────────────────────
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
  const { user }    = useAuthStore()
  const unreadCount = useNotificationStore(s => s.unreadCount)

  // Primary telemetry — first frame available across all drones
  const frames = useTelemetryStore(s => s.frames)
  const primary = Object.values(frames)[0] ?? null

  const [time, setTime]       = useState(new Date())
  const [connected, setConnected] = useState(0)

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    const poll = async () => {
      try {
        const { data } = await droneControlApi.status()
        setConnected(data.drones?.filter((d: any) => d.connected).length ?? 0)
      } catch { /* offline */ }
    }
    poll()
    const t = setInterval(poll, 5000)
    return () => clearInterval(t)
  }, [])

  const utc = time.toISOString().slice(11, 19)

  // ── chip state derivations ──
  const linkTone   = connected > 0 ? 'ok' : 'danger'
  const linkLabel  = connected > 0 ? `${connected} LINK${connected > 1 ? 'S' : ''}` : 'OFFLINE'

  const armedTone  = primary?.is_armed ? 'danger' : 'ok'
  const armedLabel = primary?.is_armed ? 'ARMED' : 'SAFE'

  const mode        = primary?.flight_mode ?? null
  const modeTone: 'ok'|'warn'|'teal'|'' =
    mode === 'AUTO' ? 'ok' : (mode === 'RTL' || mode === 'LAND') ? 'warn' : mode ? 'teal' : ''

  const bat     = primary?.battery_remaining_pct ?? -1
  const batTone = bat < 0 ? '' : bat <= 15 ? 'danger' : bat <= 25 ? 'warn' : 'ok'
  const batLabel = bat >= 0 ? `BAT ${bat}%` : 'BAT —'

  const sats      = primary?.gps_satellites ?? -1
  const gpsTone: 'ok'|'warn'|'' = sats >= 6 ? 'ok' : sats >= 0 ? 'warn' : ''
  const gpsLabel  = sats >= 0 ? `${sats} SAT` : 'GPS —'

  return (
    <header
      className="flex items-center gap-3 px-4 shrink-0 overflow-x-auto"
      style={{
        height: 44,
        background: 'rgba(8,16,28,0.92)',
        borderBottom: '1px solid var(--da-border)',
        backdropFilter: 'blur(12px)',
      }}>

      {/* Workspace label — display font */}
      <span className="display font-semibold text-sm shrink-0" style={{ color: '#94a3b8', minWidth: 160 }}>
        {LABELS[workspace]}
      </span>

      {/* ── Status chip strip ── */}
      <div className="flex items-center gap-1.5 flex-1 overflow-x-auto" style={{ scrollbarWidth: 'none' }}>

        {/* LINK */}
        <Chip tone={linkTone}>
          {linkLabel}
        </Chip>

        {/* ARMED — only show when telemetry is present */}
        {primary && (
          <Chip tone={armedTone}>{armedLabel}</Chip>
        )}

        {/* FLIGHT MODE */}
        {mode && (
          <Chip tone={modeTone} dot={false}>{mode}</Chip>
        )}

        {/* BATTERY */}
        {bat >= 0 && (
          <Chip tone={batTone as any}>{batLabel}</Chip>
        )}

        {/* GPS */}
        {sats >= 0 && (
          <Chip tone={gpsTone as any}>{gpsLabel}</Chip>
        )}
      </div>

      {/* UTC clock */}
      <span className="mono text-xs shrink-0" style={{ color: '#4b5563' }}>{utc} UTC</span>

      {/* Notification bell */}
      <button
        onClick={onNotifClick}
        className="relative w-8 h-8 flex items-center justify-center rounded transition-colors shrink-0"
        style={{ color: unreadCount > 0 ? '#f59e0b' : '#6b7280' }}>
        <Bell size={16} />
        {unreadCount > 0 && (
          <span
            className="absolute -top-0.5 -right-0.5 flex items-center justify-center rounded-full"
            style={{
              width: 16, height: 16,
              background: '#ef4444',
              fontSize: 9, fontWeight: 700, color: 'white',
            }}>
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {/* User info */}
      <div className="text-xs shrink-0" style={{ color: '#6b7280' }}>
        <span style={{ color: '#94a3b8' }}>{(user as any)?.username ?? 'operator'}</span>
        <span className="ml-2 mono text-[10px] px-1.5 py-0.5 rounded"
          style={{ background: 'rgba(59,130,246,0.15)', color: '#3b82f6' }}>
          {(user as any)?.role ?? 'viewer'}
        </span>
      </div>
    </header>
  )
}

export default TopBar
