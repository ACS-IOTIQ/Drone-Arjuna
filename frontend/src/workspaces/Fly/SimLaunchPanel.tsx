import { useEffect, useState } from 'react'
import { Play, Cpu } from 'lucide-react'
import { useMissionStore } from '@/store/missionStore'
import { useFleetStore } from '@/store/fleetStore'
import { droneControlApi, SimStartPayload } from '@/api/droneControl'

interface Props {
  onStarted: () => void
}

export default function SimLaunchPanel({ onStarted }: Props) {
  const { missions, fetchMissions } = useMissionStore()
  const { instances } = useFleetStore()

  const [missionId,  setMissionId]  = useState<number | ''>('')
  const [droneId,    setDroneId]    = useState<number | ''>('')
  const [speedMult,  setSpeedMult]  = useState(1)
  const [launching,  setLaunching]  = useState(false)
  const [err,        setErr]        = useState('')

  useEffect(() => { fetchMissions() }, [])

  // Auto-fill drone when mission changes
  useEffect(() => {
    if (!missionId) return
    const m = missions.find(m => m.id === Number(missionId))
    if (m?.drone_instance_id) setDroneId(m.drone_instance_id)
  }, [missionId])

  const start = async () => {
    if (!missionId || !droneId) { setErr('Select a mission and a drone'); return }
    setLaunching(true); setErr('')
    try {
      const payload: SimStartPayload = {
        mission_id:         Number(missionId),
        drone_instance_id:  Number(droneId),
        speed_multiplier:   speedMult,
      }
      await droneControlApi.simulateStart(payload)
      await useFleetStore.getState().fetchConnections()
      onStarted()
    } catch (e: any) {
      setErr(e.response?.data?.detail ?? 'Failed to start simulation')
    } finally {
      setLaunching(false)
    }
  }

  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center z-[998]"
      style={{ background: 'rgba(10,14,26,0.88)' }}>
      <div className="da-card w-full max-w-sm p-6 flex flex-col gap-4"
        style={{ backdropFilter: 'blur(12px)' }}>

        <div className="flex items-center gap-2.5 mb-1">
          <div className="w-8 h-8 rounded flex items-center justify-center"
            style={{ background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.3)' }}>
            <Cpu size={16} style={{ color: '#3b82f6' }} />
          </div>
          <div>
            <h3 className="font-semibold text-sm">Mission Simulation</h3>
            <p className="text-[11px]" style={{ color: '#4b5563' }}>
              Fly a mission without a physical drone
            </p>
          </div>
        </div>

        {/* Mission */}
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>MISSION</span>
          <select className="da-input" value={missionId}
            onChange={e => setMissionId(e.target.value ? Number(e.target.value) : '')}>
            <option value="">— Select mission —</option>
            {missions.map(m => (
              <option key={m.id} value={m.id}>{m.name} · {m.mission_type}</option>
            ))}
          </select>
          {missions.length === 0 && (
            <p className="text-[10px]" style={{ color: '#4b5563' }}>
              No missions saved. Create one in the Plan workspace first.
            </p>
          )}
        </label>

        {/* Drone */}
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>SIMULATED DRONE</span>
          <select className="da-input" value={droneId}
            onChange={e => setDroneId(e.target.value ? Number(e.target.value) : '')}>
            <option value="">— Select drone —</option>
            {instances.map(d => (
              <option key={d.id} value={d.id}>{d.call_sign}</option>
            ))}
          </select>
        </label>

        {/* Speed multiplier */}
        <div className="flex flex-col gap-1.5">
          <span className="text-[10px] font-medium" style={{ color: '#94a3b8' }}>
            SIMULATION SPEED — {speedMult}×
          </span>
          <div className="grid grid-cols-4 gap-1.5">
            {[1, 2, 5, 10].map(s => (
              <button key={s} onClick={() => setSpeedMult(s)}
                className="py-1.5 rounded text-xs font-medium transition-all"
                style={{
                  background: speedMult === s ? 'rgba(59,130,246,0.2)' : 'rgba(255,255,255,0.04)',
                  color:      speedMult === s ? '#3b82f6' : '#6b7280',
                  border:     `1px solid ${speedMult === s ? '#3b82f6' : 'var(--da-border)'}`,
                }}>
                {s}×
              </button>
            ))}
          </div>
          <p className="text-[10px]" style={{ color: '#374151' }}>
            Higher speeds compress flight time — HUD and telemetry run at full fidelity regardless.
          </p>
        </div>

        {err && <p className="text-xs" style={{ color: '#ef4444' }}>{err}</p>}

        <button onClick={start}
          disabled={launching || !missionId || !droneId}
          className="da-btn da-btn-primary justify-center mt-1">
          <Play size={14} />
          {launching ? 'Starting…' : 'Start Simulation'}
        </button>
      </div>
    </div>
  )
}
