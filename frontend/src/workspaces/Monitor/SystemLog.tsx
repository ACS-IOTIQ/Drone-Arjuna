/**
 * SystemLog
 * Live scrolling log of system events shown in the Monitor workspace.
 * Pulls from notificationStore (connection events, command results,
 * health alerts) and the telemetry store (mode/arm state changes).
 */
import { useEffect, useRef, useState } from 'react'
import { Download, Filter, Trash2 } from 'lucide-react'
import { useNotificationStore, NotifLevel } from '@/store/notificationStore'
import { useTelemetryStore } from '@/store/telemetryStore'
import { useFleetStore } from '@/store/fleetStore'

interface LogEntry {
  id:        number
  ts:        Date
  level:     NotifLevel | 'debug'
  source:    string
  message:   string
  droneId?:  number
}

let _eid = 0
const _log: LogEntry[] = []
const _listeners = new Set<() => void>()

export function appendLog(entry: Omit<LogEntry, 'id' | 'ts'>) {
  _log.unshift({ ...entry, id: ++_eid, ts: new Date() })
  if (_log.length > 500) _log.splice(500)
  _listeners.forEach(fn => fn())
}

const LEVEL_COLOR: Record<string, string> = {
  danger:  '#ef4444',
  warning: '#f59e0b',
  success: '#22c55e',
  info:    '#3b82f6',
  debug:   '#4b5563',
}

type Filter = 'all' | NotifLevel | 'debug'

export default function SystemLog({ droneId }: { droneId?: number }) {
  const [entries, setEntries]     = useState<LogEntry[]>([])
  const [filter, setFilter]       = useState<Filter>('all')
  const [autoScroll, setAutoScroll] = useState(true)
  const bottomRef                 = useRef<HTMLDivElement>(null)

  // Subscribe to global log store
  useEffect(() => {
    const refresh = () => setEntries([..._log])
    _listeners.add(refresh)
    refresh()
    return () => { _listeners.delete(refresh) }
  }, [])

  // Bridge notifications → log
  const notifications = useNotificationStore(s => s.notifications)
  const prevCountRef  = useRef(0)
  useEffect(() => {
    const latest = notifications.slice(0, notifications.length - prevCountRef.current)
    latest.forEach(n => {
      appendLog({ level: n.level, source: 'health', message: n.message, droneId: n.droneId })
    })
    prevCountRef.current = notifications.length
  }, [notifications])

  // Bridge telemetry mode/arm changes → log
  const frames   = useTelemetryStore(s => s.frames)
  const prevRef  = useRef<Record<number, { mode: string; armed: boolean }>>({})
  const { instances, connections } = useFleetStore()

  useEffect(() => {
    instances.filter(d => connections[d.id]).forEach(d => {
      const f    = frames[d.id]
      const prev = prevRef.current[d.id]
      if (!f) return
      if (prev) {
        if (f.flight_mode !== prev.mode) {
          appendLog({
            level: 'info', source: 'drone_control',
            message: `${d.call_sign} mode changed: ${prev.mode} → ${f.flight_mode}`,
            droneId: d.id,
          })
        }
        if (f.is_armed !== prev.armed) {
          appendLog({
            level:   f.is_armed ? 'warning' : 'success',
            source:  'drone_control',
            message: `${d.call_sign} ${f.is_armed ? 'ARMED' : 'DISARMED'}`,
            droneId: d.id,
          })
        }
      }
      prevRef.current[d.id] = { mode: f.flight_mode, armed: f.is_armed }
    })
  }, [frames])

  // Auto-scroll
  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries, autoScroll])

  const visible = entries.filter(e => {
    if (droneId && e.droneId && e.droneId !== droneId) return false
    if (filter === 'all') return true
    return e.level === filter
  })

  const exportCsv = () => {
    const rows = visible.map(e =>
      `${e.ts.toISOString()},${e.level},${e.source},"${e.message.replace(/"/g, '""')}"`
    )
    const blob = new Blob(
      [`timestamp,level,source,message\n${rows.join('\n')}`],
      { type: 'text/csv' },
    )
    const a = Object.assign(document.createElement('a'), {
      href:     URL.createObjectURL(blob),
      download: `dronearjuna-log-${Date.now()}.csv`,
    })
    a.click()
  }

  return (
    <div className="da-card flex flex-col" style={{ height: 320 }}>
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 shrink-0"
        style={{ borderBottom: '1px solid var(--da-border)' }}>
        <Filter size={13} style={{ color: '#6b7280' }} />
        <span className="text-xs font-semibold mr-1" style={{ color: '#6b7280' }}>
          System Log
        </span>
        <div className="flex gap-1 flex-1">
          {(['all', 'danger', 'warning', 'info', 'debug'] as Filter[]).map(f => (
            <button key={f}
              onClick={() => setFilter(f)}
              className="text-xs px-2 py-0.5 rounded"
              style={{
                background: filter === f ? 'rgba(255,255,255,0.08)' : 'transparent',
                color:      f === 'all'  ? '#94a3b8' : LEVEL_COLOR[f],
                border:     `1px solid ${filter === f ? 'var(--da-border)' : 'transparent'}`,
              }}>
              {f}
            </button>
          ))}
        </div>
        <button onClick={() => { _log.splice(0); setEntries([]) }}
          className="p-1" style={{ color: '#6b7280' }} title="Clear log">
          <Trash2 size={13} />
        </button>
        <button onClick={exportCsv}
          className="p-1" style={{ color: '#6b7280' }} title="Export CSV">
          <Download size={13} />
        </button>
        <label className="flex items-center gap-1 text-xs cursor-pointer"
          style={{ color: '#6b7280' }}>
          <input type="checkbox" checked={autoScroll}
            onChange={e => setAutoScroll(e.target.checked)} />
          Auto
        </label>
      </div>

      {/* Entries */}
      <div className="flex-1 overflow-y-auto">
        {visible.length === 0 ? (
          <div className="flex items-center justify-center h-full"
            style={{ color: '#374151', fontSize: 12 }}>
            No log entries
          </div>
        ) : (
          [...visible].reverse().map(e => (
            <div key={e.id}
              className="flex items-start gap-2 px-3 py-1.5"
              style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
              <span className="mono text-[10px] shrink-0 mt-0.5"
                style={{ color: '#374151', minWidth: 60 }}>
                {e.ts.toLocaleTimeString()}
              </span>
              <span className="text-[10px] font-semibold shrink-0 uppercase"
                style={{ color: LEVEL_COLOR[e.level] ?? '#94a3b8', minWidth: 48 }}>
                {e.level}
              </span>
              <span className="text-[10px] shrink-0"
                style={{ color: '#4b5563', minWidth: 80 }}>
                [{e.source}]
              </span>
              <span className="text-xs" style={{ color: '#94a3b8', wordBreak: 'break-word' }}>
                {e.message}
              </span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}