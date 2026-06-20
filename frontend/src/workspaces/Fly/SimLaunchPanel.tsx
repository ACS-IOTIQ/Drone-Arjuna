import { useEffect, useState } from 'react'
import { Cpu, Play } from 'lucide-react'
import { useMissionStore } from '@/store/missionStore'
import { useFleetStore } from '@/store/fleetStore'
import { droneControlApi, SimStartPayload } from '@/api/droneControl'

interface Props {
  onStarted: () => void
}

export default function SimLaunchPanel({ onStarted }: Props) {
  const { missions, fetchMissions } = useMissionStore()
  const { instances, fetchInstances } = useFleetStore()

  const [missionId, setMissionId] = useState<number | ''>('')
  const [droneId, setDroneId] = useState<number | ''>('')
  const [speedMult, setSpeedMult] = useState(1)
  const [launching, setLaunching] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    fetchMissions()
    fetchInstances()
  }, [])

  useEffect(() => {
    if (!missionId) return
    const mission = missions.find(m => m.id === Number(missionId))
    if (mission?.drone_instance_id) setDroneId(mission.drone_instance_id)
  }, [missionId, missions])

  const start = async () => {
    if (!missionId || !droneId) { setErr('Select a mission and a drone'); return }
    setLaunching(true); setErr('')
    try {
      const payload: SimStartPayload = {
        mission_id: Number(missionId),
        drone_instance_id: Number(droneId),
        speed_multiplier: speedMult,
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
    <div className="absolute inset-0 z-[998] flex items-center justify-center p-4"
      style={{ background: 'rgba(241,245,249,0.86)' }}>
      <div className="da-card w-full max-w-sm p-6 flex flex-col gap-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded"
            style={{ background: '#dbeafe', border: '1px solid #bfdbfe' }}>
            <Cpu size={17} style={{ color: '#2563eb' }} />
          </div>
          <div>
            <h3 className="font-semibold text-sm">Mission Simulation</h3>
            <p className="text-[11px]" style={{ color: '#64748b' }}>
              Fly a saved mission without connecting hardware.
            </p>
          </div>
        </div>

        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-medium" style={{ color: '#64748b' }}>MISSION</span>
          <select className="da-input" value={missionId}
            onChange={e => setMissionId(e.target.value ? Number(e.target.value) : '')}>
            <option value="">Select mission</option>
            {missions.map(m => (
              <option key={m.id} value={m.id}>{m.name} - {m.mission_type}</option>
            ))}
          </select>
          {missions.length === 0 && (
            <p className="text-[10px]" style={{ color: '#64748b' }}>
              No missions saved. Create one in the Plan workspace first.
            </p>
          )}
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-medium" style={{ color: '#64748b' }}>SIMULATED DRONE</span>
          <select className="da-input" value={droneId}
            onChange={e => setDroneId(e.target.value ? Number(e.target.value) : '')}>
            <option value="">Select drone</option>
            {instances.map(d => (
              <option key={d.id} value={d.id}>{d.call_sign}</option>
            ))}
          </select>
          {instances.length === 0 && (
            <p className="text-[10px]" style={{ color: '#64748b' }}>
              Register a drone in Settings before launching simulation.
            </p>
          )}
        </label>

        <div className="flex flex-col gap-1.5">
          <span className="text-[10px] font-medium" style={{ color: '#64748b' }}>
            SIMULATION SPEED - {speedMult}x
          </span>
          <div className="grid grid-cols-4 gap-1.5">
            {[1, 2, 5, 10].map(speed => (
              <button key={speed} onClick={() => setSpeedMult(speed)}
                className="rounded py-1.5 text-xs font-medium transition-all"
                style={{
                  background: speedMult === speed ? '#dbeafe' : '#ffffff',
                  color: speedMult === speed ? '#2563eb' : '#334155',
                  border: `1px solid ${speedMult === speed ? '#93c5fd' : 'var(--da-border)'}`,
                }}>
                {speed}x
              </button>
            ))}
          </div>
          <p className="text-[10px]" style={{ color: '#64748b' }}>
            Higher speeds compress flight time. HUD and telemetry still run at full fidelity.
          </p>
        </div>

        {err && <p className="rounded bg-red-50 px-3 py-2 text-xs text-red-700">{err}</p>}

        <button onClick={start}
          disabled={launching || !missionId || !droneId}
          className="da-btn da-btn-primary justify-center">
          <Play size={14} />
          {launching ? 'Starting...' : 'Start Simulation'}
        </button>
      </div>
    </div>
  )
}
