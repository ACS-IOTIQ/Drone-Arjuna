
// ═══════════════════════════════════════════════════════════════
// AltitudeGauge.tsx
// Vertical tape with dual AGL / MSL readout.
// ═══════════════════════════════════════════════════════════════
interface AltGaugeProps {
  altAgl:   number
  altMsl:   number
  maxAlt?:  number    // for scale reference
  showLabel?: boolean
}

export function AltitudeGauge({ altAgl, altMsl, maxAlt = 500, showLabel = true }: AltGaugeProps) {
  const pct  = Math.min(100, Math.max(0, (altAgl / maxAlt) * 100))
  const warn = altAgl > maxAlt * 0.85
  const color = warn ? '#ef4444' : altAgl > 0 ? '#3b82f6' : '#6b7280'

  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 4, minWidth: 56 }}>
      {/* Vertical tape */}
      <div style={{
        width: 16, height: 72, borderRadius: 8,
        background: 'var(--da-border)', position: 'relative', overflow: 'hidden',
      }}>
        <div style={{
          position: 'absolute', bottom: 0, width: '100%',
          height: `${pct}%`, borderRadius: 8,
          background: color, transition: 'height 0.4s ease, background 0.3s',
        }} />
      </div>
      {/* Values */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
        <span style={{
          fontSize: 14, fontWeight: 600, color,
          fontFamily: 'JetBrains Mono, monospace', lineHeight: 1,
        }}>
          {altAgl.toFixed(1)}
        </span>
        <span style={{ fontSize: 9, color: '#6b7280' }}>AGL m</span>
        <span style={{
          fontSize: 10, color: '#4b5563',
          fontFamily: 'JetBrains Mono, monospace',
        }}>
          {altMsl.toFixed(0)}
        </span>
        <span style={{ fontSize: 9, color: '#374151' }}>MSL m</span>
      </div>
      {showLabel && (
        <span style={{ fontSize: 10, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Alt
        </span>
      )}
    </div>
  )
}

