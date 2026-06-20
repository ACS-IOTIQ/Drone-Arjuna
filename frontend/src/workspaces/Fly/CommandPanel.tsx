
// ═══════════════════════════════════════════
// CommandPanel.tsx
// ═══════════════════════════════════════════
import { useState } from 'react'
import { AlertTriangle, ChevronDown } from 'lucide-react'
import { droneControlApi } from '@/api/droneControl'
import { useTelemetryStore } from '@/store/telemetryStore'

const MODES = ['STABILIZE', 'ALT_HOLD', 'LOITER', 'AUTO', 'GUIDED', 'RTL', 'LAND']

export function CommandPanel({ droneId }: { droneId: number }) {
  const frame = useTelemetryStore(s => s.frames[droneId])
  const [confirm, setConfirm] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const send = async (cmd: string, params = {}) => {
    setBusy(true)
    try {
      await droneControlApi.command({ drone_id: droneId, command: cmd as any, params })
    } finally {
      setBusy(false)
      setConfirm(null)
    }
  }

  const safeCmd = (cmd: string, params = {}) => {
    setConfirm(cmd)
  }

  return (
    <div className="da-card flex flex-col gap-2 p-3"
      style={{ background: 'rgba(255,255,255,0.95)', backdropFilter: 'blur(8px)' }}>

      <p className="text-[10px] font-semibold" style={{ color: '#475569' }}>FLIGHT COMMANDS</p>

      {/* Arm / Disarm */}
      <div className="grid grid-cols-2 gap-1.5">
        <button
          disabled={busy || frame?.is_armed}
          onClick={() => setConfirm('arm')}
          className="da-btn da-btn-success justify-center text-xs py-2">
          Arm
        </button>
        <button
          disabled={busy || !frame?.is_armed}
          onClick={() => setConfirm('disarm')}
          className="da-btn da-btn-ghost justify-center text-xs py-2">
          Disarm
        </button>
      </div>

      {/* Takeoff, visible when armed and on the ground */}
      {frame?.is_armed && (frame?.alt_agl ?? 0) < 2 && (
        <button
          disabled={busy}
          onClick={() => send('takeoff', { altitude: 30 })}
          className="da-btn da-btn-primary justify-center text-xs py-2 font-semibold">
          Takeoff
        </button>
      )}

      {/* Mode buttons */}
      <div className="flex flex-col gap-1">
        <p className="text-[10px]" style={{ color: '#4b5563' }}>SET MODE</p>
        {['LOITER', 'AUTO', 'GUIDED'].map(m => (
          <button key={m}
            disabled={busy || frame?.flight_mode === m}
            onClick={() => send('set_mode', { mode: m })}
            className="da-btn da-btn-ghost justify-between text-xs py-1.5"
            style={{ opacity: frame?.flight_mode === m ? 0.5 : 1 }}>
            {m}
            {frame?.flight_mode === m && <span style={{ color: '#22c55e', fontSize: 9 }}>ACTIVE</span>}
          </button>
        ))}
      </div>

      {/* RTL + Land — highlighted */}
      <div className="flex flex-col gap-1">
        <button disabled={busy} onClick={() => setConfirm('rtl')}
          className="da-btn justify-center text-xs py-2 font-semibold"
          style={{ background: 'rgba(245,158,11,0.15)', color: '#f59e0b',
            border: '1px solid rgba(245,158,11,0.3)' }}>
          Return to Launch
        </button>
        <button disabled={busy} onClick={() => setConfirm('land')}
          className="da-btn justify-center text-xs py-2"
          style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6',
            border: '1px solid rgba(59,130,246,0.2)' }}>
          Land Now
        </button>
      </div>

      {/* Emergency stop */}
      <button disabled={busy} onClick={() => setConfirm('emergency_stop')}
        className="da-btn da-btn-danger justify-center text-xs py-2.5 font-bold tracking-wide mt-1">
        EMERGENCY STOP
      </button>

      {/* Confirm dialog */}
      {confirm && (
        <div className="mt-1 p-2 rounded flex flex-col gap-2"
          style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)' }}>
          <div className="flex items-center gap-1.5 text-xs" style={{ color: '#f87171' }}>
            <AlertTriangle size={12} />
            Confirm: <strong>{confirm.toUpperCase()}</strong>
          </div>
          <div className="flex gap-1.5">
            <button onClick={() => setConfirm(null)}
              className="da-btn da-btn-ghost text-xs py-1 flex-1">Cancel</button>
            <button onClick={() => send(confirm)}
              className="da-btn da-btn-danger text-xs py-1 flex-1">Confirm</button>
          </div>
        </div>
      )}
    </div>
  )
}

export default CommandPanel
