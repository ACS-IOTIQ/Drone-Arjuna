import { useState } from 'react'
import { Square, Pause, Play, SkipForward } from 'lucide-react'
import { useTelemetryStore } from '@/store/telemetryStore'
import { useFleetStore } from '@/store/fleetStore'
import { droneControlApi } from '@/api/droneControl'

const PHASE_COLOR: Record<string, string> = {
  idle:    '#6b7280',
  armed:   '#f59e0b',
  takeoff: '#22c55e',
  flying:  '#3b82f6',
  paused:  '#f59e0b',
  rtl:     '#f97316',
  landing: '#06b6d4',
  landed:  '#22c55e',
}

function formatEndurance(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds)) return null
  const total = Math.max(0, Math.round(seconds))
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, '0')} remaining`
}

function formatDistance(meters: number | null | undefined): string | null {
  if (meters == null || !Number.isFinite(meters)) return null
  if (meters >= 1000) return `${(meters / 1000).toFixed(2)} km to destination`
  return `${Math.round(meters)} m to destination`
}

const PHASE_LABEL: Record<string, string> = {
  idle:    'IDLE',
  armed:   'ARMED',
  takeoff: 'TAKEOFF',
  flying:  'FLYING',
  paused:  'LOITER',
  rtl:     'RTL',
  landing: 'LANDING',
  landed:  'LANDED',
}

interface Props {
  droneId: number
  onStopped: () => void
}

export default function SimProgressOverlay({ droneId, onStopped }: Props) {
  const frame = useTelemetryStore(s => s.frames[droneId]) as any
  const [stopping, setStopping] = useState(false)

  if (!frame?.sim_phase) return null

  const phase    = frame.sim_phase as string
  const progress = (frame.sim_progress  ?? 0) as number
  const wpIdx    = (frame.sim_waypoint_idx   ?? 0) as number
  const wpCount  = (frame.sim_waypoint_count ?? 0) as number
  const color    = PHASE_COLOR[phase] ?? '#6b7280'
  const endurance = formatEndurance(frame.estimated_endurance_s)
  const destDistance = formatDistance(frame.distance_to_destination_m)
  const batteryRtl = Boolean(frame.battery_rtl_triggered)

  const cmd = (action: string, params: Record<string, unknown> = {}) =>
    droneControlApi.command({ drone_id: droneId, command: action as any, params })

  const stopSim = async () => {
    setStopping(true)
    try {
      await droneControlApi.simulateStop(droneId)
    } catch {
      // A 404 here just means the flight already ended on its own (e.g. it
      // landed and auto-cleaned up) — that's the same end state as a
      // successful stop, so fall through and refresh/close either way.
    } finally {
      await useFleetStore.getState().fetchConnections()
      onStopped()
      setStopping(false)
    }
  }

  return (
    <footer className="da-sim-progress">
      <div className="da-sim-progress-identity">
        <span className="da-sim-phase"
          style={{ background: color + '18', color, borderColor: color + '55' }}>
          {PHASE_LABEL[phase] ?? phase.toUpperCase()}
        </span>
        <div>
          <strong>{frame.call_sign}</strong>
          <span>
            {frame.battery_remaining_pct >= 0 ? `${frame.battery_remaining_pct}% battery` : 'Simulation'}
            {endurance ? ` · ${endurance}` : ''}
          </span>
        </div>
      </div>

      {batteryRtl && (
        <div style={{
          fontSize: '11px', color: '#f97316', background: 'rgba(249,115,22,0.12)',
          border: '1px solid rgba(249,115,22,0.3)', borderRadius: 4,
          padding: '4px 8px', margin: '4px 0',
        }}>
          Battery insufficient to reach remaining waypoints — auto-RTL in progress
        </div>
      )}

      <div className="da-sim-progress-track">
        <div>
          <span>{wpCount > 0 ? `Waypoint ${Math.min(wpIdx + 1, wpCount)} / ${wpCount}` : 'Mission progress'}</span>
          <b>{Math.round(progress * 100)}%</b>
        </div>
        {destDistance && (
          <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: 2 }}>
            {destDistance}
          </div>
        )}
        <div className="da-sim-progress-rail">
          <i style={{ width: `${Math.max(0, Math.min(100, progress * 100))}%`, background: color }} />
        </div>
      </div>

      <div className="da-sim-progress-actions">

          {phase === 'idle' && (
            <button onClick={() => cmd('arm')}
              className="da-btn da-btn-success justify-center">
              Arm
            </button>
          )}

          {phase === 'armed' && (
            <button onClick={() => cmd('takeoff', { altitude: 30 })}
              className="da-btn da-btn-primary justify-center">
              <Play size={11} /> Takeoff
            </button>
          )}

          {phase === 'flying' && (
            <button onClick={() => cmd('set_mode', { mode: 'LOITER' })}
              className="da-btn da-btn-ghost justify-center">
              <Pause size={11} /> Pause
            </button>
          )}

          {phase === 'paused' && (
            <button onClick={() => cmd('set_mode', { mode: 'AUTO' })}
              className="da-btn da-btn-ghost justify-center">
              <Play size={11} /> Resume
            </button>
          )}

          {['flying', 'paused', 'takeoff'].includes(phase) && (
            <button onClick={() => cmd('rtl')}
              className="da-btn justify-center"
              style={{ background: 'rgba(245,158,11,0.12)', color: '#f59e0b',
                border: '1px solid rgba(245,158,11,0.25)' }}>
              <SkipForward size={11} /> RTL
            </button>
          )}

          {['flying', 'paused', 'takeoff'].includes(phase) && (
            <button onClick={() => cmd('land')}
              className="da-btn justify-center"
              style={{ background: 'rgba(6,182,212,0.1)', color: '#06b6d4',
                border: '1px solid rgba(6,182,212,0.2)' }}>
              Land
            </button>
          )}

          <button onClick={stopSim} disabled={stopping}
            className="da-btn justify-center shrink-0"
            style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444',
              border: '1px solid rgba(239,68,68,0.2)' }}>
            <Square size={11} />
            {stopping ? '...' : 'Stop'}
          </button>
      </div>
    </footer>
  )
}
