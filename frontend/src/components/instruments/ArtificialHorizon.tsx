// ═══════════════════════════════════════════════════════════════
// ArtificialHorizon.tsx
// SVG attitude indicator — roll rotates the horizon band,
// pitch shifts it vertically. Fixed aircraft reference in amber.
// ═══════════════════════════════════════════════════════════════
interface AHProps {
  roll:    number   // degrees
  pitch:   number   // degrees
  width?:  number
  height?: number
}

export function ArtificialHorizon({ roll, pitch, width = 160, height = 90 }: AHProps) {
  const cx = width / 2
  const cy = height / 2
  const pitchOffset = pitch * 1.5   // px per degree
  const sky    = '#1a3a5c'
  const ground = '#3d2b1a'

  return (
    <div style={{
      position: 'relative', width, height,
      borderRadius: 6, overflow: 'hidden',
      border: '1px solid var(--da-border)',
    }}>
      <svg width={width} height={height} style={{ display: 'block' }}>
        <defs>
          <clipPath id="ah-clip">
            <rect width={width} height={height} rx="6" />
          </clipPath>
        </defs>
        <g clipPath="url(#ah-clip)"
          transform={`rotate(${-roll}, ${cx}, ${cy})`}>
          <rect x={-width} y={cy - pitchOffset} width={width * 3} height={height * 3}
            fill={ground} />
          <rect x={-width} y={-height * 2} width={width * 3}
            height={height * 2 + cy - pitchOffset + 1} fill={sky} />
          <line x1={-width} y1={cy - pitchOffset} x2={width * 2} y2={cy - pitchOffset}
            stroke="rgba(255,255,255,0.4)" strokeWidth="1" />
          {[-10, -5, 5, 10].map(deg => {
            const y   = cy - pitchOffset + deg * 1.5
            const len = Math.abs(deg) === 10 ? 30 : 16
            return (
              <g key={deg}>
                <line x1={cx - len} y1={y} x2={cx + len} y2={y}
                  stroke="rgba(255,255,255,0.35)" strokeWidth="0.8" />
                <text x={cx + len + 3} y={y + 3}
                  fill="rgba(255,255,255,0.4)" fontSize="7">{Math.abs(deg)}</text>
              </g>
            )
          })}
        </g>
        {/* Fixed aircraft reference */}
        <line x1={cx - 35} y1={cy} x2={cx - 8} y2={cy}
          stroke="#f59e0b" strokeWidth="2" strokeLinecap="round" />
        <line x1={cx + 8} y1={cy} x2={cx + 35} y2={cy}
          stroke="#f59e0b" strokeWidth="2" strokeLinecap="round" />
        <circle cx={cx} cy={cy} r="2.5" fill="#f59e0b" />
      </svg>
    </div>
  )
}

export default ArtificialHorizon
