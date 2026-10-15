// ═══════════════════════════════════════════
// FlightHUD.tsx — live attitude + flight state card for the Monitor workspace.
// Styled to match the DroneArjuna light cards. Driven by telemetry frames,
// so manual control inputs show up as the drone moves.
// ═══════════════════════════════════════════
import { useTelemetryStore } from '@/store/telemetryStore'

const SIZE = 220
const C = SIZE / 2
const R = 96
const PX_PER_DEG = 3

const norm360 = (v: number) => ((v % 360) + 360) % 360
const num = (v: unknown, d = 0) => (typeof v === 'number' && Number.isFinite(v) ? v : d)

const CARDINALS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']

function Stat({ label, value, unit, color }: { label: string; value: string; unit?: string; color?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white/80 px-2.5 py-1.5">
      <div className="text-[9px] font-semibold uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mono text-sm font-bold" style={{ color: color ?? '#0f172a' }}>
        {value}<span className="ml-0.5 text-[10px] font-medium text-slate-400">{unit}</span>
      </div>
    </div>
  )
}

export function FlightHUD({ droneId }: { droneId: number }) {
  const frame = useTelemetryStore(s => s.frames[droneId])
  if (!frame) return null

  const roll = num(frame.roll_deg)
  const pitch = num(frame.pitch_deg)
  const heading = norm360(num(frame.heading))
  const climb = num(frame.climb_rate_ms)
  const armed = !!frame.is_armed
  const pOff = Math.max(-70, Math.min(70, pitch * PX_PER_DEG))
  const cardinal = CARDINALS[Math.round(heading / 45) % 8]

  return (
    <div className="da-flight-hud da-card p-3" aria-label="Flight HUD">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold">Flight HUD</h3>
        <span
          className="da-badge text-[9px]"
          style={{
            background: armed ? 'rgba(34,197,94,0.14)' : 'rgba(100,116,139,0.14)',
            color: armed ? '#16a34a' : '#64748b',
          }}>
          {armed ? 'ARMED' : 'DISARMED'} · {frame.flight_mode}
        </span>
      </div>

      <div className="flex justify-center">
        <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} style={{ maxWidth: '100%' }}>
          <defs>
            <clipPath id="fhud-clip"><circle cx={C} cy={C} r={R} /></clipPath>
            <linearGradient id="fhud-sky" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#60a5fa" /><stop offset="1" stopColor="#bfdbfe" />
            </linearGradient>
            <linearGradient id="fhud-gnd" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#a3b86c" /><stop offset="1" stopColor="#6b8e3d" />
            </linearGradient>
          </defs>

          <g clipPath="url(#fhud-clip)">
            <g transform={`rotate(${-roll} ${C} ${C})`}>
              <rect x={-SIZE} y={C + pOff - SIZE * 2} width={SIZE * 3} height={SIZE * 2} fill="url(#fhud-sky)" />
              <rect x={-SIZE} y={C + pOff} width={SIZE * 3} height={SIZE * 2} fill="url(#fhud-gnd)" />
              <line x1={-SIZE} x2={SIZE * 2} y1={C + pOff} y2={C + pOff} stroke="#fff" strokeWidth="2" />
              {[-20, -10, 10, 20].map(d => {
                const y = C + pOff - d * PX_PER_DEG
                return (
                  <g key={d}>
                    <line x1={C - 22} x2={C + 22} y1={y} y2={y} stroke="#fff" strokeWidth="1.5" opacity="0.9" />
                    <text x={C + 28} y={y + 3} fill="#fff" fontSize="9" opacity="0.9">{Math.abs(d)}</text>
                  </g>
                )
              })}
            </g>
          </g>

          {/* Bezel + roll scale */}
          <circle cx={C} cy={C} r={R} fill="none" stroke="#cbd5e1" strokeWidth="6" />
          <circle cx={C} cy={C} r={R + 5} fill="none" stroke="#e2e8f0" strokeWidth="1" />
          {[-60, -45, -30, -15, 0, 15, 30, 45, 60].map(a => {
            const rad = (a - 90) * Math.PI / 180
            const len = a % 30 === 0 ? 9 : 5
            return <line key={a}
              x1={C + (R - 3) * Math.cos(rad)} y1={C + (R - 3) * Math.sin(rad)}
              x2={C + (R - 3 - len) * Math.cos(rad)} y2={C + (R - 3 - len) * Math.sin(rad)}
              stroke="#fff" strokeWidth="1.5" />
          })}
          <g transform={`rotate(${-roll} ${C} ${C})`}>
            <polygon points={`${C},${C - R + 2} ${C - 6},${C - R + 15} ${C + 6},${C - R + 15}`} fill="#2563eb" />
          </g>

          {/* Fixed aircraft symbol */}
          <path d={`M ${C - 46} ${C} H ${C - 14} L ${C} ${C + 10} L ${C + 14} ${C} H ${C + 46}`}
            fill="none" stroke="#0f172a" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />
          <circle cx={C} cy={C} r="2.5" fill="#0f172a" />
        </svg>
      </div>

      {/* Heading strip */}
      <div className="relative mx-auto mt-2 h-9 w-full overflow-hidden rounded-xl border border-slate-200 bg-white/80">
        <svg width="100%" height="36" viewBox="0 0 300 36" preserveAspectRatio="none">
          {Array.from({ length: 19 }, (_, i) => {
            const d = Math.round(heading / 10) * 10 + (i - 9) * 10
            const x = 150 + (d - heading) * 3
            const label = norm360(d)
            const major = label % 45 === 0
            return (
              <g key={d}>
                <line x1={x} x2={x} y1={major ? 20 : 26} y2={34} stroke="#94a3b8" />
                {major && <text x={x} y={16} textAnchor="middle" fontSize="10" fontWeight="700"
                  fill={label === 0 ? '#dc2626' : '#475569'}>{CARDINALS[label / 45]}</text>}
              </g>
            )
          })}
          <polygon points="145,0 155,0 150,7" fill="#2563eb" />
        </svg>
        <div className="mono pointer-events-none absolute right-2 top-1 text-xs font-bold text-slate-900">
          {heading.toFixed(0)}° {cardinal}
        </div>
      </div>

      <div className="mt-2 grid grid-cols-3 gap-2">
        <Stat label="Roll" value={roll.toFixed(1)} unit="°" />
        <Stat label="Pitch" value={pitch.toFixed(1)} unit="°" />
        <Stat label="Alt AGL" value={num(frame.alt_agl).toFixed(1)} unit="m" />
        <Stat label="Gnd Spd" value={num(frame.groundspeed_ms).toFixed(1)} unit="m/s" />
        <Stat label="Air Spd" value={num(frame.airspeed_ms).toFixed(1)} unit="m/s" />
        <Stat label="Climb" value={`${climb > 0 ? '+' : ''}${climb.toFixed(1)}`} unit="m/s"
          color={Math.abs(climb) > 5 ? '#d97706' : undefined} />
      </div>
    </div>
  )
}

export default FlightHUD
