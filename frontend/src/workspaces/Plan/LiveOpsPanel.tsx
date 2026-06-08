// ═══════════════════════════════════════════════════════════════
// src/workspaces/Plan/LiveOpsPanel.tsx
// Right-side live ops panel for the Plan workspace.
// Shows real-time telemetry metrics + quick command buttons for
// the first connected drone, without duplicating the Fly workspace.
// ═══════════════════════════════════════════════════════════════
import { useState } from 'react'
import {
  Activity, Zap, Navigation, Battery, Satellite,
  Home, PlaneLanding, Pause, ShieldAlert,
} from 'lucide-react'
import { useTelemetryStore } from '@/store/telemetryStore'
import { useFleetStore } from '@/store/fleetStore'
import { droneControlApi } from '@/api/droneControl'

// ── tiny helpers ──────────────────────────────────────────────
function Metric({ icon, label, value, tone = 'neutral' }: {
  icon: React.ReactNode
  label: string
  value: string
  tone?: 'ok' | 'warn' | 'danger' | 'teal' | 'neutral'
}) {
  const colors: Record<string, string> = {
    ok:      '#22c55e',
    warn:    '#f59e0b',
    danger:  '#ef4444',
    teal:    'var(--da-teal)',
    neutral: '#94a3b8',
  }
  return (
    <div className="flex items-center gap-2 px-3 py-2"
      style={{ borderBottom: '1px solid var(--da-border)' }}>
      <span style={{ color: colors[tone], flexShrink: 0 }}>{icon}</span>
      <div className="flex-1 min-w-0">
        <div className="text-[9px] tracking-widest" style={{ color: '#374151' }}>{label}</div>
        <div className="mono text-xs font-medium truncate" style={{ color: colors[tone] }}>{value}</div>
      </div>
    </div>
  )
}

function CmdBtn({ label, icon, color, onClick, disabled, danger }: {
  label: string
  icon: React.ReactNode
  color: string
  onClick: () => void
  disabled?: boolean
  danger?: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex flex-col items-center justify-center gap-1 rounded py-2 transition-all"
      style={{
        background: danger ? 'rgba(239,68,68,0.08)' : `rgba(0,0,0,0)`,
        border: `1px solid ${disabled ? 'var(--da-border)' : color}`,
        color: disabled ? '#374151' : color,
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
      }}>
      {icon}
      <span className="text-[9px] font-semibold tracking-wider">{label}</span>
    </button>
  )
}

export default function LiveOpsPanel() {
  const frames      = useTelemetryStore(s => s.frames)
  const { instances, connections } = useFleetStore()
  const [cmdErr, setCmdErr] = useState('')
  const [busy,   setBusy]   = useState(false)

  // Pick the first connected drone
  const activeDrone = instances.find(d => connections[d.id])
  const frame       = activeDrone ? frames[activeDrone.id] : null

  const sendCmd = async (command: string, params?: Record<string, unknown>) => {
    if (!activeDrone) return
    setBusy(true); setCmdErr('')
    try {
      await droneControlApi.command({
        drone_id: activeDrone.id,
        command: command as any,
        params,
      })
    } catch (e: any) {
      setCmdErr(e.response?.data?.detail ?? 'Command failed')
    } finally {
      setBusy(false)
    }
  }

  // Derived display values
  const altStr   = frame ? `${frame.alt_agl.toFixed(1)} m AGL` : '— m AGL'
  const spdStr   = frame ? `${frame.groundspeed_ms.toFixed(1)} m/s` : '— m/s'
  const batStr   = frame
    ? frame.battery_remaining_pct >= 0
      ? `${frame.battery_remaining_pct.toFixed(0)} % · ${frame.battery_voltage_v.toFixed(1)} V`
      : `${frame.battery_voltage_v.toFixed(1)} V`
    : '— %'
  const satStr   = frame ? `${frame.gps_satellites} sats · ${frame.gps_fix_type}` : '—'
  const modeStr  = frame ? frame.flight_mode : 'NO DRONE'

  const batTone  = !frame ? 'neutral'
    : frame.battery_remaining_pct < 15 ? 'danger'
    : frame.battery_remaining_pct < 30 ? 'warn'
    : 'ok'

  const gpsTone  = !frame ? 'neutral'
    : frame.gps_satellites < 6 ? 'warn'
    : frame.gps_fix_type === 'No GPS' ? 'danger'
    : 'ok'

  const modeTone: 'ok' | 'teal' | 'warn' = !frame ? 'warn'
    : frame.is_armed ? 'danger' as any
    : 'teal'

  return (
    <div className="flex flex-col h-full overflow-hidden"
      style={{ background: 'var(--da-surface)', borderLeft: '1px solid var(--da-border)' }}>

      {/* Header */}
      <div className="px-3 py-2.5 shrink-0 flex items-center justify-between"
        style={{ borderBottom: '1px solid var(--da-border)', background: 'rgba(59,130,246,0.05)' }}>
        <span className="display font-semibold text-xs tracking-widest" style={{ color: '#64748b' }}>
          LIVE OPS
        </span>
        {activeDrone && (
          <span className="mono text-[10px]" style={{ color: '#3b82f6' }}>
            {activeDrone.call_sign}
          </span>
        )}
      </div>

      {!activeDrone ? (
        <div className="flex-1 flex items-center justify-center p-4">
          <p className="text-[11px] text-center" style={{ color: '#374151' }}>
            No drone connected.<br />Connect from Fleet workspace.
          </p>
        </div>
      ) : (
        <>
          {/* Telemetry metrics */}
          <div className="shrink-0">
            <Metric icon={<Navigation size={13} />}  label="ALTITUDE"   value={altStr}  tone="teal" />
            <Metric icon={<Activity    size={13} />}  label="SPEED"      value={spdStr}  tone="neutral" />
            <Metric icon={<Zap         size={13} />}  label="MODE"       value={modeStr} tone={modeTone} />
            <Metric icon={<Battery     size={13} />}  label="BATTERY"    value={batStr}  tone={batTone} />
            <Metric icon={<Satellite   size={13} />}  label="GPS"        value={satStr}  tone={gpsTone} />
          </div>

          {/* Armed status chip */}
          {frame && (
            <div className="px-3 py-2 shrink-0" style={{ borderBottom: '1px solid var(--da-border)' }}>
              <span className={`da-chip ${frame.is_armed ? 'danger' : 'ok'}`}>
                <span className="da-chip-dot" />
                {frame.is_armed ? 'ARMED' : 'DISARMED'}
              </span>
            </div>
          )}

          {/* Quick commands */}
          <div className="p-3 shrink-0">
            <p className="text-[9px] tracking-widest mb-2" style={{ color: '#374151' }}>
              QUICK COMMANDS
            </p>
            <div className="grid grid-cols-2 gap-2">
              <CmdBtn label="RTL"     icon={<Home        size={15} />} color="#3b82f6"
                onClick={() => sendCmd('rtl')}  disabled={busy} />
              <CmdBtn label="LAND"    icon={<PlaneLanding size={15} />} color="#22c55e"
                onClick={() => sendCmd('land')} disabled={busy} />
              <CmdBtn label="HOLD"    icon={<Pause       size={15} />} color="#f59e0b"
                onClick={() => sendCmd('set_mode', { mode: 'LOITER' })} disabled={busy} />
              <CmdBtn label="E-STOP" icon={<ShieldAlert  size={15} />} color="#ef4444"
                onClick={() => sendCmd('emergency_stop')} disabled={busy} danger />
            </div>

            {/* Arm / Disarm */}
            {frame && (
              <button
                onClick={() => sendCmd(frame.is_armed ? 'disarm' : 'arm')}
                disabled={busy}
                className="w-full mt-2 py-2 rounded text-xs font-semibold transition-all"
                style={{
                  background: frame.is_armed ? 'rgba(239,68,68,0.12)' : 'rgba(34,197,94,0.1)',
                  border:     frame.is_armed ? '1px solid rgba(239,68,68,0.4)' : '1px solid rgba(34,197,94,0.35)',
                  color:      frame.is_armed ? '#ef4444' : '#22c55e',
                  opacity: busy ? 0.5 : 1,
                }}>
                {frame.is_armed ? '⚡ DISARM' : '⚡ ARM'}
              </button>
            )}
          </div>

          {cmdErr && (
            <p className="text-[10px] px-3 pb-2" style={{ color: '#f87171' }}>{cmdErr}</p>
          )}

          <div className="flex-1" />

          {/* Footer: coordinates */}
          {frame && (
            <div className="px-3 py-2 shrink-0 mono"
              style={{ borderTop: '1px solid var(--da-border)', color: '#374151', fontSize: 9 }}>
              <div>{frame.lat.toFixed(6)}°N</div>
              <div>{frame.lon.toFixed(6)}°E</div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
