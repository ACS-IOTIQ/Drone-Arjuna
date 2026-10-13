/**
 * BlackBox
 * Persistent record of drone issues (battery, link, GPS, geofence, proximity,
 * auto-RTL, mode/arm changes) read from the backend `drone_events` table.
 * Unlike SystemLog, this survives page reloads and is kept for a year.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Download, RefreshCw } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import { droneControlApi, DroneEventRow, DroneEventSeverity } from '@/api/droneControl'

const SEV_COLOR: Record<DroneEventSeverity, string> = {
  critical: '#ef4444',
  warning:  '#f59e0b',
  info:     '#3b82f6',
  resolved: '#22c55e',
}

const RANGES = [
  { key: '1h',  label: '1 h',  ms: 3_600_000 },
  { key: '24h', label: '24 h', ms: 86_400_000 },
  { key: '7d',  label: '7 d',  ms: 7 * 86_400_000 },
  { key: '30d', label: '30 d', ms: 30 * 86_400_000 },
] as const

type Filter = 'all' | DroneEventSeverity

export default function BlackBox({ droneId }: { droneId: number }) {
  const [rows, setRows]       = useState<DroneEventRow[]>([])
  const [range, setRange]     = useState<(typeof RANGES)[number]['key']>('24h')
  const [filter, setFilter]   = useState<Filter>('all')
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)
  const [open, setOpen]       = useState<string | null>(null)

  const load = useCallback(async () => {
    const ms = RANGES.find(r => r.key === range)!.ms
    setLoading(true)
    try {
      const res = await droneControlApi.events(droneId, {
        start: new Date(Date.now() - ms).toISOString(),
        limit: 2000,
      })
      setRows(res.data)
      setError(null)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Could not load black-box events')
    } finally {
      setLoading(false)
    }
  }, [droneId, range])

  // Initial load + refresh every 10 s so new issues appear without a reload.
  useEffect(() => {
    load()
    const t = setInterval(load, 10_000)
    return () => clearInterval(t)
  }, [load])

  const visible = useMemo(
    () => rows.filter(r => filter === 'all' || r.severity === filter),
    [rows, filter],
  )

  // Issues per severity over time — bucket width scales with the selected range.
  const chartData = useMemo(() => {
    const ms = RANGES.find(r => r.key === range)!.ms
    const bucket = ms / 24
    const now = Date.now()
    const start = now - ms
    const buckets = Array.from({ length: 24 }, (_, i) => ({
      t: start + i * bucket,
      critical: 0, warning: 0, info: 0, resolved: 0,
    }))
    for (const r of rows) {
      const i = Math.min(23, Math.floor((new Date(r.timestamp).getTime() - start) / bucket))
      if (i >= 0) buckets[i][r.severity]++
    }
    return buckets
  }, [rows, range])

  const counts = useMemo(() => {
    const c = { critical: 0, warning: 0, info: 0, resolved: 0 }
    rows.forEach(r => { c[r.severity]++ })
    return c
  }, [rows])

  const fmtTick = (t: number) => {
    const d = new Date(t)
    return range === '1h' || range === '24h'
      ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      : d.toLocaleDateString([], { month: 'short', day: 'numeric' })
  }

  const exportCsv = () => {
    const esc = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`
    const csv = [
      'timestamp,event_type,severity,message,value,lat,lng,alt,mission_id,snapshot',
      ...visible.map(r => [
        r.timestamp, r.event_type, r.severity, r.message, r.value,
        r.lat, r.lng, r.alt, r.mission_id, JSON.stringify(r.snapshot ?? {}),
      ].map(esc).join(',')),
    ].join('\n')
    const a = Object.assign(document.createElement('a'), {
      href: URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' })),
      download: `drone-${droneId}-blackbox.csv`,
    })
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="da-card min-w-0 p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">Black Box</h3>
          <p className="text-[11px]" style={{ color: '#64748b' }}>
            Recorded drone issues · {rows.length} events
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          {RANGES.map(r => (
            <button key={r.key} onClick={() => setRange(r.key)}
              className="text-xs px-2 py-0.5 rounded"
              style={{
                color: range === r.key ? '#e2e8f0' : '#6b7280',
                background: range === r.key ? 'rgba(255,255,255,0.08)' : 'transparent',
                border: '1px solid var(--da-border)',
              }}>
              {r.label}
            </button>
          ))}
          <button className="da-btn da-btn-ghost text-xs" onClick={load} title="Refresh">
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          </button>
          <button className="da-btn da-btn-ghost text-xs" onClick={exportCsv}
            disabled={visible.length === 0} title="Export CSV">
            <Download size={13} /> CSV
          </button>
        </div>
      </div>

      {/* Severity summary / filter */}
      <div className="flex flex-wrap gap-2">
        {(['all', 'critical', 'warning', 'info', 'resolved'] as Filter[]).map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className="text-xs px-2 py-0.5 rounded uppercase font-semibold"
            style={{
              color: f === 'all' ? '#94a3b8' : SEV_COLOR[f],
              border: `1px solid ${filter === f ? (f === 'all' ? '#94a3b8' : SEV_COLOR[f]) : 'var(--da-border)'}`,
              background: filter === f ? 'rgba(255,255,255,0.05)' : 'transparent',
            }}>
            {f}{f !== 'all' ? ` ${counts[f]}` : ''}
          </button>
        ))}
      </div>

      {/* Timeline chart */}
      <div style={{ height: 140 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--da-border)" />
            <XAxis dataKey="t" tickFormatter={fmtTick} tick={{ fontSize: 10, fill: '#6b7280' }}
              interval={3} />
            <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: '#6b7280' }} />
            <Tooltip
              labelFormatter={(t: number) => new Date(t).toLocaleString()}
              contentStyle={{
                background: 'var(--da-card)', border: '1px solid var(--da-border)',
                fontSize: 12, borderRadius: 6,
              }} />
            <Bar dataKey="critical" stackId="a" fill={SEV_COLOR.critical} isAnimationActive={false} />
            <Bar dataKey="warning"  stackId="a" fill={SEV_COLOR.warning}  isAnimationActive={false} />
            <Bar dataKey="info"     stackId="a" fill={SEV_COLOR.info}     isAnimationActive={false} />
            <Bar dataKey="resolved" stackId="a" fill={SEV_COLOR.resolved} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Event list */}
      {error && <p className="text-xs" style={{ color: '#ef4444' }}>{error}</p>}
      <div className="overflow-y-auto" style={{ maxHeight: 280 }}>
        {visible.length === 0 ? (
          <p className="text-xs py-6 text-center" style={{ color: '#374151' }}>
            {loading ? 'Loading…' : 'No issues recorded in this period'}
          </p>
        ) : visible.map(r => {
          const id = `${r.timestamp}-${r.event_type}`
          return (
            <div key={id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <button className="flex w-full items-start gap-2 px-1 py-1.5 text-left"
                onClick={() => setOpen(open === id ? null : id)}>
                <span className="mono text-[10px] shrink-0 mt-0.5" style={{ color: '#4b5563', minWidth: 118 }}>
                  {new Date(r.timestamp).toLocaleString()}
                </span>
                <span className="text-[10px] font-semibold uppercase shrink-0 mt-0.5"
                  style={{ color: SEV_COLOR[r.severity], minWidth: 56 }}>
                  {r.severity}
                </span>
                <span className="text-xs" style={{ color: '#94a3b8', wordBreak: 'break-word' }}>
                  {r.message}
                </span>
              </button>
              {open === id && (
                <div className="mono text-[11px] px-2 pb-2 grid grid-cols-1 sm:grid-cols-2 gap-x-6"
                  style={{ color: '#64748b' }}>
                  <span>type: {r.event_type}</span>
                  {r.mission_id != null && <span>mission: {r.mission_id}</span>}
                  {r.lat != null && r.lng != null &&
                    <span>pos: {r.lat.toFixed(5)}, {r.lng.toFixed(5)}</span>}
                  {r.alt != null && <span>alt AGL: {r.alt.toFixed(1)} m</span>}
                  {r.snapshot && Object.entries(r.snapshot).map(([k, v]) => (
                    <span key={k}>{k}: {typeof v === 'number' ? Number(v.toFixed(2)) : String(v)}</span>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
