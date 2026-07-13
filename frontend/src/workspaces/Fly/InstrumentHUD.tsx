
// ═══════════════════════════════════════════
// InstrumentHUD.tsx
// ═══════════════════════════════════════════
import { useMemo } from 'react'
import { useTelemetryStore } from '@/store/telemetryStore'
import { useMissionStore } from '@/store/missionStore'
import { getZoneRule } from '@/utils/geofenceZones'
import { findRegulatoryZone } from '@/utils/regulatoryZones'
import { Battery, Compass, Satellite, Wifi } from 'lucide-react'

export function InstrumentHUD({ droneId }: { droneId: number }) {
  const frame = useTelemetryStore(s => s.frames[droneId])
  const geofence = useMissionStore(s => s.geofence)
  const zoneRule = useMemo(() => {
    if (!frame) return null
    return getZoneRule(frame.lat, frame.lon, geofence)
  }, [frame, geofence])
  const regulatoryZone = useMemo(() => {
    if (!frame) return null
    return findRegulatoryZone(frame.lat, frame.lon)
  }, [frame])

  if (!frame) return null

  const battColor = frame.battery_remaining_pct > 50 ? '#22c55e'
    : frame.battery_remaining_pct > 20 ? '#f59e0b' : '#ef4444'

  const modeColor = frame.flight_mode === 'AUTO' ? '#22c55e'
    : ['RTL', 'LAND'].some(m => frame.flight_mode?.includes(m)) ? '#f59e0b' : '#3b82f6'

  const isSimulated = !!(frame as any).sim_phase

  return (
    <div className="flex flex-col gap-2" style={{ minWidth: 220 }}>
      {/* Compass indicator */}
      <div className="da-card p-3"
        style={{ background: 'rgba(255,255,255,0.95)', backdropFilter: 'blur(8px)' }}>
        <CompassInstrument heading={frame.heading} roll={frame.roll_deg} pitch={frame.pitch_deg} />
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

        {zoneRule && (
          <div className="rounded border px-2 py-1.5 text-[10px]" style={{
            background: frame.geofence_breach ? 'rgba(254,242,242,0.95)' : 'rgba(248,250,252,0.95)',
            borderColor: frame.geofence_breach ? '#fda4af' : '#e2e8f0',
            color: frame.geofence_breach ? '#b91c1c' : '#334155',
          }}>
            <div className="font-semibold">{zoneRule.label}</div>
            <div className="mt-0.5">Alt: ≤ {zoneRule.maxAltitudeM} m · Speed: ≤ {zoneRule.maxSpeedMs} m/s</div>
            <div className="mt-0.5 text-[9px] uppercase tracking-wide">Recommended: {zoneRule.recommendedAltitudeM} m / {zoneRule.recommendedSpeedMs} m/s</div>
            {regulatoryZone && (
              <div className="mt-1 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[9px] text-amber-800">
                Govt zone: {regulatoryZone.name}
              </div>
            )}
          </div>
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

function CompassInstrument({ heading, roll, pitch }: { heading: number; roll: number; pitch: number }) {
  const normalized = ((heading % 360) + 360) % 360
  const cardinal = normalized < 45 || normalized >= 315 ? 'N'
    : normalized < 135 ? 'E'
    : normalized < 225 ? 'S'
    : 'W'

  return (
    <div className="flex items-center gap-3">
      <div
        style={{
          width: 96,
          height: 96,
          borderRadius: '50%',
          position: 'relative',
          background: 'linear-gradient(180deg, #f8fafc 0%, #e2e8f0 100%)',
          border: '1px solid rgba(15,23,42,0.16)',
          boxShadow: 'inset 0 0 0 7px rgba(255,255,255,0.75)',
          flexShrink: 0,
        }}>
        {[
          ['N', 0, '#dc2626'],
          ['E', 90, '#475569'],
          ['S', 180, '#475569'],
          ['W', 270, '#475569'],
        ].map(([label, deg, color]) => (
          <span
            key={label}
            style={{
              position: 'absolute',
              left: '50%',
              top: '50%',
              transform: `translate(-50%, -50%) rotate(${deg}deg) translateY(-37px) rotate(${-deg}deg)`,
              fontSize: 11,
              fontWeight: 800,
              color: String(color),
            }}>
            {label}
          </span>
        ))}
        <div
          style={{
            position: 'absolute',
            inset: 12,
            borderRadius: '50%',
            border: '1px dashed rgba(71,85,105,0.28)',
            transform: `rotate(${normalized}deg)`,
            transition: 'transform 0.15s linear',
          }}>
          <div
            style={{
              position: 'absolute',
              left: '50%',
              top: 5,
              transform: 'translateX(-50%)',
              width: 0,
              height: 0,
              borderLeft: '7px solid transparent',
              borderRight: '7px solid transparent',
              borderBottom: '30px solid #2563eb',
            }}
          />
        </div>
        <div
          style={{
            position: 'absolute',
            left: '50%',
            top: '50%',
            transform: 'translate(-50%, -50%)',
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: '#0f172a',
            border: '2px solid #ffffff',
          }}
        />
      </div>

      <div className="flex flex-1 flex-col gap-1">
        <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider" style={{ color: '#64748b' }}>
          <Compass size={12} /> Heading
        </div>
        <div className="mono text-2xl font-bold leading-none" style={{ color: '#0f172a' }}>
          {normalized.toFixed(0)} deg
        </div>
        <div className="text-xs font-semibold" style={{ color: '#2563eb' }}>{cardinal}</div>
        <div className="mt-1 grid grid-cols-2 gap-1 text-[10px]">
          <div className="rounded border border-slate-200 bg-white/70 px-1.5 py-1">
            <span style={{ color: '#64748b' }}>Roll</span>
            <span className="mono ml-1" style={{ color: '#0f172a' }}>{roll.toFixed(0)} deg</span>
          </div>
          <div className="rounded border border-slate-200 bg-white/70 px-1.5 py-1">
            <span style={{ color: '#64748b' }}>Pitch</span>
            <span className="mono ml-1" style={{ color: '#0f172a' }}>{pitch.toFixed(0)} deg</span>
          </div>
        </div>
      </div>
    </div>
  )
}

export default InstrumentHUD
