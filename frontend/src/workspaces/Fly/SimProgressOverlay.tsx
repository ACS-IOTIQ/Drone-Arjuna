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

  const cmd = (action: string, params: Record<string, unknown> = {}) =>
    droneControlApi.command({ drone_id: droneId, command: action as any, params })

  const stopSim = async () => {
    setStopping(true)
    try {
      await droneControlApi.simulateStop()
      await useFleetStore.getState().fetchConnections()
      onStopped()
    } finally {
      setStopping(false)
    }
  }

  return (
    <div className="absolute bottom-4 left-1/2 z-[999]"
      style={{ transform: 'translateX(-50%)', minWidth: 360, maxWidth: 420 }}>
      <div className="da-card px-4 py-3 flex flex-col gap-2.5"
        style={{ background: 'rgba(255,255,255,0.96)', backdropFilter: 'blur(10px)' }}>

        {/* Phase badge + drone name */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 rounded text-[10px] font-bold tracking-widest"
              style={{ background: color + '22', color, border: `1px solid ${color}44` }}>
              {PHASE_LABEL[phase] ?? phase.toUpperCase()}
            </span>
            <span className="text-xs font-medium" style={{ color: '#94a3b8' }}>
              SIM - {frame.call_sign}
            </span>
          </div>
          <span className="text-[10px] mono" style={{ color: '#374151' }}>
            {frame.battery_remaining_pct >= 0 ? `${frame.battery_remaining_pct}%` : ''}
          </span>
        </div>

        {/* Waypoint progress bar */}
        {wpCount > 0 && (
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between">
              <span className="text-[10px]" style={{ color: '#4b5563' }}>
                Waypoint {Math.min(wpIdx + 1, wpCount)} / {wpCount}
              </span>
              <span className="text-[10px] mono" style={{ color: '#4b5563' }}>
                {Math.round(progress * 100)}%
              </span>
            </div>
            <div className="h-1 rounded-full overflow-hidden"
              style={{ background: '#e2e8f0' }}>
              <div className="h-full rounded-full transition-all duration-500"
                style={{ width: `${progress * 100}%`, background: color }} />
            </div>
          </div>
        )}

        {/* Context-sensitive controls */}
        <div className="flex items-center gap-1.5">

          {phase === 'idle' && (
            <button onClick={() => cmd('arm')}
              className="da-btn da-btn-success text-xs py-1.5 flex-1 justify-center">
              Arm
            </button>
          )}

          {phase === 'armed' && (
            <button onClick={() => cmd('takeoff', { altitude: 30 })}
              className="da-btn da-btn-primary text-xs py-1.5 flex-1 justify-center">
              <Play size={11} /> Takeoff
            </button>
          )}

          {phase === 'flying' && (
            <button onClick={() => cmd('set_mode', { mode: 'LOITER' })}
              className="da-btn da-btn-ghost text-xs py-1.5 flex-1 justify-center">
              <Pause size={11} /> Pause
            </button>
          )}

          {phase === 'paused' && (
            <button onClick={() => cmd('set_mode', { mode: 'AUTO' })}
              className="da-btn da-btn-ghost text-xs py-1.5 flex-1 justify-center">
              <Play size={11} /> Resume
            </button>
          )}

          {['flying', 'paused', 'takeoff'].includes(phase) && (
            <button onClick={() => cmd('rtl')}
              className="da-btn text-xs py-1.5 flex-1 justify-center"
              style={{ background: 'rgba(245,158,11,0.12)', color: '#f59e0b',
                border: '1px solid rgba(245,158,11,0.25)' }}>
              <SkipForward size={11} /> RTL
            </button>
          )}

          {['flying', 'paused', 'takeoff'].includes(phase) && (
            <button onClick={() => cmd('land')}
              className="da-btn text-xs py-1.5 flex-1 justify-center"
              style={{ background: 'rgba(6,182,212,0.1)', color: '#06b6d4',
                border: '1px solid rgba(6,182,212,0.2)' }}>
              Land
            </button>
          )}

          <button onClick={stopSim} disabled={stopping}
            className="da-btn text-xs py-1.5 px-3 justify-center shrink-0"
            style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444',
              border: '1px solid rgba(239,68,68,0.2)' }}>
            <Square size={11} />
            {stopping ? '...' : 'Stop'}
          </button>
        </div>

      </div>
    </div>
  )
}
