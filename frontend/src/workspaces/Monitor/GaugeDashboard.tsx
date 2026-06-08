import { useTelemetryStore } from '@/store/telemetryStore'

interface GaugeDef {
  key:       string
  label:     string
  unit:      string
  max:       number
  warnAt?:   number
  dangerAt?: number
  decimals?: number
}

const GAUGES: GaugeDef[] = [
  { key: 'battery_remaining_pct', label: 'Battery',    unit: '%',   max: 100, warnAt: 25,  dangerAt: 15  },
  { key: 'alt_agl',               label: 'Altitude',   unit: 'm',   max: 500, decimals: 1  },
  { key: 'groundspeed_ms',        label: 'GND Speed',  unit: 'm/s', max: 30,  decimals: 1  },
  { key: 'gps_satellites',        label: 'GPS Sats',   unit: '',    max: 20,  warnAt: 6,  dangerAt: 4  },
  { key: 'rssi',                  label: 'RSSI',       unit: '',    max: 255, warnAt: 80, dangerAt: 40 },
  { key: 'cpu_load_pct',          label: 'CPU Load',   unit: '%',   max: 100, warnAt: 70, dangerAt: 90 },
]

interface Props { droneId: number }

export default function GaugeDashboard({ droneId }: Props) {
  const frame = useTelemetryStore(s => s.frames[droneId])

  return (
    <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))' }}>
      {GAUGES.map(g => (
        <GaugeCard key={g.key} def={g} value={(frame as any)?.[g.key] ?? 0} />
      ))}
    </div>
  )
}

function GaugeCard({ def, value }: { def: GaugeDef; value: number }) {
  const pct       = Math.min(100, Math.max(0, (value / def.max) * 100))
  const isDanger  = def.dangerAt !== undefined && value <= def.dangerAt
  const isWarn    = !isDanger && def.warnAt !== undefined && value <= def.warnAt
  const color     = isDanger ? '#ef4444' : isWarn ? '#f59e0b' : '#22c55e'
  const formatted = typeof value === 'number'
    ? value.toFixed(def.decimals ?? 0)
    : String(value)

  return (
    <div className="da-card px-3 py-3 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs" style={{ color: '#6b7280' }}>{def.label}</span>
        <span className="text-xs font-semibold mono" style={{ color }}>
          {formatted}{def.unit}
        </span>
      </div>
      {/* Progress bar */}
      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--da-border)' }}>
        <div className="h-full rounded-full"
          style={{
            width:      `${pct}%`,
            background: color,
            transition: 'width 0.3s ease, background 0.3s',
          }} />
      </div>
      {/* Min/max labels */}
      <div className="flex justify-between">
        <span className="text-[9px]" style={{ color: '#374151' }}>0</span>
        <span className="text-[9px]" style={{ color: '#374151' }}>{def.max}{def.unit}</span>
      </div>
    </div>
  )
}