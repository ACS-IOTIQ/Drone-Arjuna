
// ═══════════════════════════════════════════════════════════════
// BatteryGauge.tsx
// Arc gauge with colour-coded fill.
// ═══════════════════════════════════════════════════════════════
interface BattGaugeProps {
  value:       number         // 0–100 percent
  voltage?:    number         // optional V display
  size?:       'sm' | 'md'
  showLabel?:  boolean
}

export function BatteryGauge({ value, voltage, size = 'md', showLabel = true }: BattGaugeProps) {
  const dim   = size === 'sm' ? 64 : 88
  const r     = (dim / 2) - 8
  const cx    = dim / 2
  const cy    = dim / 2
  const circ  = 2 * Math.PI * r
  // Show 270° arc (from 135° to 405°)
  const arcLen = circ * 0.75
  const filled = arcLen * (Math.max(0, Math.min(100, value)) / 100)
  const gap    = arcLen - filled

  const color = value > 50 ? '#22c55e' : value > 20 ? '#f59e0b' : '#ef4444'

  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
      <div style={{ position: 'relative', width: dim, height: dim }}>
        <svg width={dim} height={dim} style={{ transform: 'rotate(135deg)' }}>
          {/* Track */}
          <circle cx={cx} cy={cy} r={r}
            fill="none" stroke="var(--da-border)" strokeWidth="5"
            strokeDasharray={`${arcLen} ${circ - arcLen}`}
            strokeLinecap="round" />
          {/* Fill */}
          <circle cx={cx} cy={cy} r={r}
            fill="none" stroke={color} strokeWidth="5"
            strokeDasharray={`${filled} ${gap + circ - arcLen}`}
            strokeLinecap="round"
            style={{ transition: 'stroke-dasharray 0.5s ease, stroke 0.3s' }} />
        </svg>
        {/* Centre label */}
        <div style={{
          position: 'absolute', inset: 0,
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
        }}>
          <span style={{
            fontSize: size === 'sm' ? 13 : 17,
            fontWeight: 600, color,
            fontFamily: 'JetBrains Mono, monospace',
          }}>
            {value >= 0 ? `${value}%` : '—'}
          </span>
          {voltage !== undefined && (
            <span style={{ fontSize: 9, color: '#6b7280', marginTop: 1 }}>
              {voltage.toFixed(1)}V
            </span>
          )}
        </div>
      </div>
      {showLabel && (
        <span style={{ fontSize: 10, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Battery
        </span>
      )}
    </div>
  )
}

