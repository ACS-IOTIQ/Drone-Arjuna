
// ═══════════════════════════════════════════
// InstrumentHUD.tsx
// ═══════════════════════════════════════════
import { useTelemetryStore } from '@/store/telemetryStore'
import { Battery, Satellite, Wifi, Wind } from 'lucide-react'

export function InstrumentHUD({ droneId }: { droneId: number }) {
  const frame = useTelemetryStore(s => s.frames[droneId])
  if (!frame) return null

  const battColor = frame.battery_remaining_pct > 50 ? '#22c55e'
    : frame.battery_remaining_pct > 20 ? '#f59e0b' : '#ef4444'

  const modeColor = frame.flight_mode === 'AUTO' ? '#22c55e'
    : ['RTL', 'LAND'].some(m => frame.flight_mode?.includes(m)) ? '#f59e0b' : '#3b82f6'

  const isSimulated = !!(frame as any).sim_phase

  return (
    <div className="flex flex-col gap-2" style={{ minWidth: 220 }}>
      {/* Attitude indicator */}
      <div className="da-card p-3"
        style={{ background: 'rgba(255,255,255,0.95)', backdropFilter: 'blur(8px)' }}>
        <ArtificialHorizon roll={frame.roll_deg} pitch={frame.pitch_deg} />
        {isSimulated && (
          <div className="mt-1.5 text-center text-[9px] font-bold tracking-widest"
            style={{ color: '#22c55e', opacity: 0.7 }}>
            SIMULATED DATA
          </div>
        )}
      </div>

      {/* Core stats */}
      <div className="da-card px-3 py-2 flex flex-col gap-1.5"
        style={{ background: 'rgba(255,255,255,0.95)', backdropFilter: 'blur(8px)' }}>

        <HUDRow label="ALT AGL"  val={`${frame.alt_agl.toFixed(1)} m`}  />
        <HUDRow label="ALT MSL"  val={`${frame.alt_msl.toFixed(1)} m`} secondary />
        <HUDRow label="GND SPD"  val={`${frame.groundspeed_ms.toFixed(1)} m/s`} />
        <HUDRow label="AIRSPEED" val={`${frame.airspeed_ms.toFixed(1)} m/s`} secondary />
        <HUDRow label="CLIMB"    val={`${frame.climb_rate_ms > 0 ? '+' : ''}${frame.climb_rate_ms.toFixed(1)} m/s`}
          color={Math.abs(frame.climb_rate_ms) > 5 ? '#f59e0b' : undefined} />
        <HUDRow label="HEADING"  val={`${frame.heading.toFixed(0)}°`} />

        <div className="flex items-center justify-between pt-1"
          style={{ borderTop: '1px solid var(--da-border)' }}>
          <div className="flex items-center gap-1">
            <Battery size={12} style={{ color: battColor }} />
            <span className="text-xs mono" style={{ color: battColor }}>
              {frame.battery_remaining_pct >= 0 ? `${frame.battery_remaining_pct}%` : 'N/A'}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <Satellite size={12} style={{ color: '#6b7280' }} />
            <span className="text-xs mono" style={{ color: '#94a3b8' }}>{frame.gps_satellites}</span>
          </div>
          <div className="flex items-center gap-1">
            <Wifi size={12} style={{ color: '#6b7280' }} />
            <span className="text-xs mono" style={{ color: '#94a3b8' }}>{frame.rssi}</span>
          </div>
          <span className="da-badge text-[9px]"
            style={{ background: modeColor + '22', color: modeColor, border: `1px solid ${modeColor}44` }}>
            {frame.flight_mode}
          </span>
        </div>

        {frame.is_armed && (
          <div className="text-center py-0.5 rounded text-[10px] font-bold tracking-widest animate-pulse"
            style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>ARMED</div>
        )}
      </div>
    </div>
  )
}

function HUDRow({ label, val, secondary, color }: {
  label: string; val: string; secondary?: boolean; color?: string
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[10px] font-medium" style={{ color: '#4b5563' }}>{label}</span>
      <span className={`text-xs mono ${secondary ? 'opacity-60' : ''}`}
        style={{ color: color ?? '#94a3b8' }}>{val}</span>
    </div>
  )
}

function ArtificialHorizon({ roll, pitch }: { roll: number; pitch: number }) {
  const W = 160, H = 90, cx = W / 2, cy = H / 2
  const pitchOffset = pitch * 1.5   // px per degree
  const sky = '#1a3a5c', ground = '#3d2b1a'

  return (
    <div style={{ position: 'relative', width: W, height: H, borderRadius: 6, overflow: 'hidden',
      border: '1px solid var(--da-border)' }}>
      <svg width={W} height={H} style={{ display: 'block' }}>
        <defs>
          <clipPath id="horizon-clip">
            <rect width={W} height={H} rx="6" />
          </clipPath>
        </defs>
        <g clipPath="url(#horizon-clip)"
          transform={`rotate(${-roll}, ${cx}, ${cy})`}>
          {/* Ground */}
          <rect x={-W} y={cy - pitchOffset} width={W * 3} height={H * 3}
            fill={ground} />
          {/* Sky */}
          <rect x={-W} y={-H * 2} width={W * 3} height={H * 2 + cy - pitchOffset + 1}
            fill={sky} />
          {/* Horizon line */}
          <line x1={-W} y1={cy - pitchOffset} x2={W * 2} y2={cy - pitchOffset}
            stroke="rgba(255,255,255,0.4)" strokeWidth="1" />
          {/* Pitch ladder */}
          {[-10, -5, 5, 10].map(deg => {
            const y = cy - pitchOffset + deg * 1.5
            const len = deg % 10 === 0 ? 30 : 16
            return (
              <g key={deg}>
                <line x1={cx - len} y1={y} x2={cx + len} y2={y}
                  stroke="rgba(255,255,255,0.35)" strokeWidth="0.8" />
                <text x={cx + len + 3} y={y + 3} fill="rgba(255,255,255,0.4)"
                  fontSize="7">{Math.abs(deg)}</text>
              </g>
            )
          })}
        </g>
        {/* Fixed aircraft reference */}
        <line x1={cx - 35} y1={cy} x2={cx - 8} y2={cy} stroke="#f59e0b" strokeWidth="2" strokeLinecap="round" />
        <line x1={cx + 8}  y1={cy} x2={cx + 35} y2={cy} stroke="#f59e0b" strokeWidth="2" strokeLinecap="round" />
        <circle cx={cx} cy={cy} r="2.5" fill="#f59e0b" />
      </svg>
    </div>
  )
}

export default InstrumentHUD
