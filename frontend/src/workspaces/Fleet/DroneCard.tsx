
// ═══════════════════════════════════════════
// DroneCard.tsx
// ═══════════════════════════════════════════
import { useTelemetryStore } from '@/store/telemetryStore'
import { Battery, Wifi, Satellite, Gauge, Navigation, Anchor, Radio, Package } from 'lucide-react'
import type { DroneInstance } from '@/store/fleetStore'
import type { NavalVessel } from '@/store/vesselStore'

interface ConnectionInfo {
  transport?: string
  hf?: {
    state: 'connected' | 'degraded' | 'lost'
    snr_db: number | null
    silence_s: number
    modem_type: string
  }
}

interface Props {
  drone: DroneInstance
  connected: boolean
  homeVessel?: NavalVessel
  connectionInfo?: ConnectionInfo
  payloadName?: string
}

export function DroneCard({ drone, connected, homeVessel, connectionInfo, payloadName }: Props) {
  const frame = useTelemetryStore(s => s.frames[drone.id])

  const battColor = !frame ? '#6b7280'
    : frame.battery_remaining_pct > 50 ? '#22c55e'
    : frame.battery_remaining_pct > 20 ? '#f59e0b' : '#ef4444'

  const modeColor = !connected ? '#374151'
    : frame?.flight_mode === 'AUTO' ? '#22c55e'
    : frame?.flight_mode?.includes('RTL') || frame?.flight_mode?.includes('LAND') ? '#f59e0b'
    : '#3b82f6'

  return (
    <div className="da-card p-4 flex flex-col gap-3 transition-all hover:border-blue-500/30">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold">{drone.call_sign}</span>
            {frame?.is_armed && (
              <span className="da-badge" style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>
                ARMED
              </span>
            )}
          </div>
          <p className="text-xs mt-0.5 mono" style={{ color: '#6b7280' }}>
            s/n {drone.serial_number}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className="da-badge" style={{
            background: connected ? 'rgba(34,197,94,0.12)' : 'rgba(55,65,81,0.5)',
            color: connected ? '#22c55e' : '#6b7280',
          }}>
            {connected ? 'ONLINE' : 'OFFLINE'}
          </span>
          {frame && (
            <span className="da-badge text-[10px] mono" style={{ background: modeColor + '22', color: modeColor }}>
              {frame.flight_mode}
            </span>
          )}
          {connectionInfo?.hf && (
            <HFLinkBadge state={connectionInfo.hf.state} snr={connectionInfo.hf.snr_db} />
          )}
        </div>
      </div>

      {/* Telemetry grid */}
      {connected && frame ? (
        <div className="grid grid-cols-2 gap-2">
          <TelRow icon={<Battery size={12} />} label="Battery"
            val={frame.battery_remaining_pct >= 0 ? `${frame.battery_remaining_pct}%` : 'N/A'}
            color={battColor} />
          <TelRow icon={<Navigation size={12} />} label="Altitude"
            val={`${frame.alt_agl.toFixed(1)} m AGL`} />
          <TelRow icon={<Gauge size={12} />} label="Speed"
            val={`${frame.groundspeed_ms.toFixed(1)} m/s`} />
          <TelRow icon={<Satellite size={12} />} label="GPS"
            val={`${frame.gps_satellites} sats · ${frame.gps_fix_type}`} />
          <TelRow icon={<Wifi size={12} />} label="RSSI"
            val={`${frame.rssi}`} />
          <TelRow icon={<Gauge size={12} />} label="Heading"
            val={`${frame.heading.toFixed(0)}°`} />
        </div>
      ) : (
        <div className="text-xs text-center py-4" style={{ color: '#374151' }}>
          {connected ? 'Waiting for telemetry…' : 'Not connected'}
        </div>
      )}

      {/* Position */}
      {frame && frame.lat !== 0 && (
        <p className="text-[11px] mono" style={{ color: '#4b5563' }}>
          {frame.lat.toFixed(6)}, {frame.lon.toFixed(6)}
        </p>
      )}

      {/* Vessel assignment */}
      {(homeVessel || payloadName) && (
        <div className="flex flex-col gap-1 pt-1 border-t border-slate-200">
          {payloadName && (
            <div className="flex items-center gap-1.5">
              <Package size={11} style={{ color: '#0f766e' }} />
              <span className="text-[11px]" style={{ color: '#0f766e' }}>{payloadName}</span>
            </div>
          )}
          {homeVessel && (
        <div className="flex items-center gap-1.5 pt-1 border-t border-white/5">
          <Anchor size={11} style={{ color: '#06b6d4' }} />
          <span className="text-[11px]" style={{ color: '#06b6d4' }}>
            {homeVessel.vessel_id}
          </span>
          {homeVessel.latitude != null ? (
            <span className="text-[11px] mono ml-auto" style={{ color: '#4b5563' }}>
              {homeVessel.heading_deg?.toFixed(0)}° · {homeVessel.speed_kts?.toFixed(1)} kts
            </span>
          ) : (
            <span className="text-[11px] ml-auto" style={{ color: '#f59e0b' }}>no vessel pos</span>
          )}
        </div>
          )}
        </div>
      )}
    </div>
  )
}

function TelRow({ icon, label, val, color }: {
  icon: React.ReactNode; label: string; val: string; color?: string
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span style={{ color: '#4b5563' }}>{icon}</span>
      <span className="text-xs" style={{ color: '#6b7280' }}>{label}</span>
      <span className="text-xs font-medium ml-auto mono" style={{ color: color ?? '#94a3b8' }}>{val}</span>
    </div>
  )
}

function HFLinkBadge({ state, snr }: { state: string; snr: number | null }) {
  const colors: Record<string, { bg: string; fg: string }> = {
    connected: { bg: 'rgba(6,182,212,0.15)', fg: '#06b6d4' },
    degraded:  { bg: 'rgba(245,158,11,0.15)', fg: '#f59e0b' },
    lost:      { bg: 'rgba(239,68,68,0.15)',  fg: '#ef4444' },
  }
  const c = colors[state] ?? colors.lost
  return (
    <span className="da-badge text-[10px] flex items-center gap-1" style={{ background: c.bg, color: c.fg }}>
      <Radio size={9} />
      HF {state.toUpperCase()}
      {snr != null && ` ${snr.toFixed(0)}dB`}
    </span>
  )
}

export default DroneCard
