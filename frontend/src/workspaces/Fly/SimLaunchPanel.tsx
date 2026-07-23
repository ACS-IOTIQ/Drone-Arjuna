import { useEffect, useState } from 'react'
import { Cpu, Play, X } from 'lucide-react'
import { useMissionStore } from '@/store/missionStore'
import { useFleetStore } from '@/store/fleetStore'
import { droneControlApi, SimStartPayload } from '@/api/droneControl'
import { droneMasterApi } from '@/api/droneMaster'

interface Props {
  onStarted: (droneId: number) => void
  onClose?: () => void
}

interface DroneType { id: number; name: string; manufacturer: string; model: string }

export default function SimLaunchPanel({ onStarted, onClose }: Props) {
  const { missions, fetchMissions } = useMissionStore()
  const { instances, connections, fetchInstances, fetchConnections } = useFleetStore()
  const availableDrones = instances.filter(d => !connections[d.id])

  const [mode, setMode] = useState<'existing' | 'new'>('existing')
  const [types, setTypes] = useState<DroneType[]>([])
  const [missionId, setMissionId] = useState<number | ''>('')
  const [droneId, setDroneId] = useState<number | ''>('')
  const [speedMult, setSpeedMult] = useState(1)
  const [launching, setLaunching] = useState(false)
  const [err, setErr] = useState('')

  // New-drone fields
  const [newTypeId, setNewTypeId]   = useState<number | ''>('')
  const [newCallSign, setNewCallSign] = useState('')
  const [newSerial, setNewSerial]     = useState('')
  const [newSysId, setNewSysId]       = useState(1)

  useEffect(() => {
    fetchMissions()
    fetchInstances()
    fetchConnections()
    droneMasterApi.listTypes().then(r => setTypes(r.data))
  }, [])

  useEffect(() => {
    if (!missionId) return
    const mission = missions.find(m => m.id === Number(missionId))
    if (mission?.drone_instance_id) setDroneId(mission.drone_instance_id)
  }, [missionId, missions])

  // Suggest a fresh call sign / serial / MAVLink sysid whenever switching to "new"
  useEffect(() => {
    if (mode !== 'new') return
    const n = instances.length + 1
    setNewCallSign(prev => prev || `DRN-${n}`)
    setNewSerial(prev => prev || `SN-${Date.now().toString().slice(-6)}`)
    const maxSys = Math.max(0, ...instances.map((d: any) => Number(d.mavlink_system_id) || 0))
    setNewSysId(maxSys + 1)
    if (!newTypeId && types.length > 0) setNewTypeId(types[0].id)
  }, [mode, types, instances])

  const start = async () => {
    if (!missionId) { setErr('Select a mission'); return }
    setLaunching(true); setErr('')
    try {
      let targetDroneId = droneId

      if (mode === 'new') {
        if (!newTypeId || !newCallSign.trim() || !newSerial.trim()) {
          setErr('Drone type, call sign, and serial number are required'); setLaunching(false); return
        }
        const created = await droneMasterApi.createDrone({
          call_sign: newCallSign.trim(),
          drone_type_id: Number(newTypeId),
          serial_number: newSerial.trim(),
          mavlink_system_id: newSysId,
        })
        targetDroneId = created.data.id
        await fetchInstances()
      }

      if (!targetDroneId) { setErr('Select a drone'); setLaunching(false); return }

      const payload: SimStartPayload = {
        mission_id: Number(missionId),
        drone_instance_id: Number(targetDroneId),
        speed_multiplier: speedMult,
      }
      const started = await droneControlApi.simulateStart(payload)
      await useFleetStore.getState().fetchConnections()
      onStarted(Number(started.data?.drone_id ?? targetDroneId))
    } catch (e: any) {
      setErr(e.response?.data?.detail ?? 'Failed to start simulation')
    } finally {
      setLaunching(false)
    }
  }

  return (
    <div className="absolute inset-0 z-[1200] flex items-center justify-center p-4"
      style={{ background: 'rgba(241,245,249,0.86)' }}>
      <div className="da-sim-launch-card da-card w-full max-w-sm p-6 flex flex-col gap-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded"
            style={{ background: '#dbeafe', border: '1px solid #bfdbfe' }}>
            <Cpu size={17} style={{ color: '#2563eb' }} />
          </div>
          <div className="flex-1">
            <h3 className="font-semibold text-sm">Mission Simulation</h3>
            <p className="text-[11px]" style={{ color: '#64748b' }}>
              Fly a saved mission without connecting hardware. Multiple drones can fly at once.
            </p>
          </div>
          {onClose && (
            <button onClick={onClose}><X size={16} style={{ color: '#6b7280' }} /></button>
          )}
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

        {/* Existing vs. New drone tabs */}
        <div className="flex gap-1.5">
          {(['existing', 'new'] as const).map(m => (
            <button key={m} onClick={() => setMode(m)}
              className="flex-1 rounded py-1.5 text-xs font-medium transition-all"
              style={{
                background: mode === m ? '#dbeafe' : '#ffffff',
                color: mode === m ? '#2563eb' : '#334155',
                border: `1px solid ${mode === m ? '#93c5fd' : 'var(--da-border)'}`,
              }}>
              {m === 'existing' ? 'Use existing drone' : '+ New drone'}
            </button>
          ))}
        </div>

        {mode === 'existing' ? (
          <label className="flex flex-col gap-1">
            <span className="text-[10px] font-medium" style={{ color: '#64748b' }}>SIMULATED DRONE</span>
            <select className="da-input" value={droneId}
              onChange={e => setDroneId(e.target.value ? Number(e.target.value) : '')}>
              <option value="">Select drone</option>
              {availableDrones.map(d => (
                <option key={d.id} value={d.id}>{d.call_sign}</option>
              ))}
            </select>
            {instances.length === 0 && (
              <p className="text-[10px]" style={{ color: '#64748b' }}>
                No drones registered yet — switch to "+ New drone" to create one.
              </p>
            )}
            {instances.length > 0 && availableDrones.length === 0 && (
              <p className="text-[10px]" style={{ color: '#64748b' }}>
                All registered drones are already connected/simulating.
              </p>
            )}
          </label>
        ) : (
          <div className="flex flex-col gap-3 p-3 rounded" style={{ border: '1px solid var(--da-border)' }}>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] font-medium" style={{ color: '#64748b' }}>DRONE TYPE</span>
              <select className="da-input" value={newTypeId}
                onChange={e => setNewTypeId(e.target.value ? Number(e.target.value) : '')}>
                <option value="">Select type</option>
                {types.map(t => (
                  <option key={t.id} value={t.id}>{t.name} — {t.manufacturer} {t.model}</option>
                ))}
              </select>
              {types.length === 0 && (
                <p className="text-[10px]" style={{ color: '#64748b' }}>
                  No drone types exist yet. Add one in Settings → Master Data → Drone Types first.
                </p>
              )}
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className="flex flex-col gap-1">
                <span className="text-[10px] font-medium" style={{ color: '#64748b' }}>CALL SIGN</span>
                <input className="da-input" value={newCallSign}
                  onChange={e => setNewCallSign(e.target.value)} />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-[10px] font-medium" style={{ color: '#64748b' }}>MAVLINK ID</span>
                <input type="number" className="da-input" value={newSysId}
                  onChange={e => setNewSysId(Number(e.target.value))} />
              </label>
            </div>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] font-medium" style={{ color: '#64748b' }}>SERIAL NUMBER</span>
              <input className="da-input" value={newSerial}
                onChange={e => setNewSerial(e.target.value)} />
            </label>
          </div>
        )}

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
          disabled={
            launching || !missionId ||
            (mode === 'existing' ? !droneId : !newTypeId || !newCallSign.trim() || !newSerial.trim())
          }
          className="da-btn da-btn-primary justify-center">
          <Play size={14} />
          {launching ? 'Starting...' : mode === 'new' ? 'Register & Start Simulation' : 'Start Simulation'}
        </button>
      </div>
    </div>
  )
}
