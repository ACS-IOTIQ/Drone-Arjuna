
// ═══════════════════════════════════════════════════════════════
// SpeedGauge.tsx
// Dual groundspeed / airspeed readout with fill bar.
// ═══════════════════════════════════════════════════════════════
interface SpeedGaugeProps {
  groundspeed: number
  airspeed:    number
  maxSpeed?:   number
  showLabel?:  boolean
}

export function SpeedGauge({ groundspeed, airspeed, maxSpeed = 30, showLabel = true }: SpeedGaugeProps) {
  const pct   = Math.min(100, (groundspeed / maxSpeed) * 100)
  const warn  = groundspeed > maxSpeed * 0.9
  const color = warn ? '#ef4444' : '#22c55e'

  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 4, minWidth: 64 }}>
      {/* Horizontal bar */}
      <div style={{
        width: 72, height: 8, borderRadius: 4,
        background: 'var(--da-border)', overflow: 'hidden',
      }}>
        <div style={{
          height: '100%', borderRadius: 4,
          width: `${pct}%`, background: color,
          transition: 'width 0.4s ease, background 0.3s',
        }} />
      </div>
      {/* Values */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <span style={{
            fontSize: 16, fontWeight: 600, color,
            fontFamily: 'JetBrains Mono, monospace', lineHeight: 1,
          }}>
            {groundspeed.toFixed(1)}
          </span>
          <span style={{ fontSize: 9, color: '#6b7280' }}>GND m/s</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <span style={{
            fontSize: 12, color: '#4b5563',
            fontFamily: 'JetBrains Mono, monospace', lineHeight: 1,
          }}>
            {airspeed.toFixed(1)}
          </span>
          <span style={{ fontSize: 9, color: '#374151' }}>AIR m/s</span>
        </div>
      </div>
      {showLabel && (
        <span style={{ fontSize: 10, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Speed
        </span>
      )}
    </div>
  )
}