import { useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { useTelemetryStore } from '@/store/telemetryStore'

interface ParamDef {
  key:   string
  label: string
  color: string
  unit:  string
  warnThreshold?: number
  dangerThreshold?: number
}

const PARAMS: ParamDef[] = [
  { key: 'alt_agl',               label: 'Altitude AGL',  color: '#3b82f6', unit: 'm'   },
  { key: 'groundspeed_ms',        label: 'Ground Speed',  color: '#22c55e', unit: 'm/s' },
  { key: 'battery_remaining_pct', label: 'Battery',       color: '#f59e0b', unit: '%',
    warnThreshold: 25, dangerThreshold: 15 },
  { key: 'climb_rate_ms',         label: 'Climb Rate',    color: '#a78bfa', unit: 'm/s' },
  { key: 'airspeed_ms',           label: 'Airspeed',      color: '#2dd4bf', unit: 'm/s' },
  { key: 'rssi',                  label: 'RSSI',          color: '#fb923c', unit: '',
    dangerThreshold: 40 },
]

interface Props {
  droneId:    number
  maxHistory?: number   // points to display — default 120
}

export default function TelemetryChart({ droneId, maxHistory = 120 }: Props) {
  const [activeParam, setActiveParam] = useState('alt_agl')
  const history = useTelemetryStore(s => s.history[droneId] ?? [])

  const param = PARAMS.find(p => p.key === activeParam) ?? PARAMS[0]

  // Downsample to maxHistory points
  const step = Math.max(1, Math.floor(history.length / maxHistory))
  const chartData = history
    .filter((_, i) => i % step === 0)
    .map((f, i) => ({
      t:     i,
      value: (f as any)[activeParam],
    }))

  const values  = chartData.map(d => d.value).filter(v => v != null)
  const minVal  = values.length ? Math.min(...values) : 0
  const maxVal  = values.length ? Math.max(...values) : 100
  const padding = (maxVal - minVal) * 0.15 || 10
  const yDomain: [number, number] = [
    Math.floor(minVal - padding),
    Math.ceil(maxVal  + padding),
  ]

  return (
    <div className="da-card p-4 flex flex-col gap-3">
      {/* Param selector */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h3 className="text-sm font-semibold">Telemetry Chart</h3>
        <div className="flex flex-wrap gap-1">
          {PARAMS.map(p => (
            <button key={p.key}
              onClick={() => setActiveParam(p.key)}
              className="da-btn text-xs py-0.5 px-2"
              style={{
                background: activeParam === p.key ? p.color + '22' : 'transparent',
                color:      activeParam === p.key ? p.color       : '#6b7280',
                border:     `1px solid ${activeParam === p.key ? p.color + '55' : 'var(--da-border)'}`,
              }}>
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Live value badge */}
      {chartData.length > 0 && (
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full animate-pulse" style={{ background: param.color }} />
          <span className="text-xs mono" style={{ color: param.color }}>
            {chartData[chartData.length - 1]?.value?.toFixed(2)}{param.unit}
          </span>
          <span className="text-xs" style={{ color: '#4b5563' }}>live</span>
        </div>
      )}

      {/* Chart */}
      <div style={{ height: 200 }}>
        {chartData.length < 2 ? (
          <div className="h-full flex items-center justify-center"
            style={{ color: '#374151', fontSize: 13 }}>
            Waiting for telemetry data…
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--da-border)" />
              <XAxis dataKey="t" hide />
              <YAxis
                domain={yDomain}
                width={44}
                tick={{ fontSize: 10, fill: '#6b7280' }}
                tickFormatter={v => `${v}${param.unit}`}
              />
              <Tooltip
                contentStyle={{
                  background: 'var(--da-card)',
                  border: '1px solid var(--da-border)',
                  fontSize: 12, borderRadius: 6,
                }}
                formatter={(v: number) => [`${v?.toFixed(2)}${param.unit}`, param.label]}
                labelFormatter={() => ''}
              />
              {/* Warning reference lines */}
              {param.warnThreshold !== undefined && (
                <ReferenceLine y={param.warnThreshold} stroke="#f59e0b"
                  strokeDasharray="4 2" strokeWidth={0.8} />
              )}
              {param.dangerThreshold !== undefined && (
                <ReferenceLine y={param.dangerThreshold} stroke="#ef4444"
                  strokeDasharray="4 2" strokeWidth={0.8} />
              )}
              <Line
                type="monotone"
                dataKey="value"
                stroke={param.color}
                dot={false}
                strokeWidth={1.5}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}