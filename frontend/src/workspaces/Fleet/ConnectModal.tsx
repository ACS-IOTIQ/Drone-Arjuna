// ═══════════════════════════════════════════════════════════════
// src/workspaces/Fleet/ConnectModal.tsx
// Connect-to-drone modal with port scan / auto-fill
// ═══════════════════════════════════════════════════════════════
import { useState, useEffect } from 'react'
import { X, Radio, ScanLine, Wifi, Usb, Cable } from 'lucide-react'
import { droneControlApi, PortInfo } from '@/api/droneControl'
import { useFleetStore } from '@/store/fleetStore'
import { useTelemetryStore } from '@/store/telemetryStore'

type Transport = 'udp' | 'tcp' | 'serial' | 'hf_serial' | 'hf_tcp'
type ModemType = 'generic' | 'harris' | 'codan' | 'barrett'

interface Props { onClose: () => void }

const HF_TRANSPORTS: Transport[] = ['hf_serial', 'hf_tcp']

// Group icon per port type
function PortTypeIcon({ type }: { type: PortInfo['type'] }) {
  const props = { size: 11, style: { flexShrink: 0 } as React.CSSProperties }
  if (type === 'serial' || type === 'usb') return <Usb    {...props} />
  if (type === 'udp')                      return <Wifi   {...props} />
  return                                          <Cable  {...props} />
}

export default function ConnectModal({ onClose }: Props) {
  const { instances } = useFleetStore()
  const subscribe       = useTelemetryStore(s => s.subscribe)
  const fetchConnections = useFleetStore(s => s.fetchConnections)

  const [droneId, setDroneId]       = useState(instances[0]?.id ?? 0)
  const [transport, setTransport]   = useState<Transport>('udp')
  const [host, setHost]             = useState('127.0.0.1')
  const [port, setPort]             = useState(14550)
  const [serialPort, setSerialPort] = useState('/dev/ttyUSB0')
  const [baud, setBaud]             = useState(57600)
  const [modemType, setModemType]   = useState<ModemType>('generic')
  const [loading, setLoading]       = useState(false)
  const [err, setErr]               = useState('')

  // ── Port scan state ────────────────────────────────────────────
  const [scanning,  setScanning]  = useState(false)
  const [portList,  setPortList]  = useState<PortInfo[] | null>(null)
  const [scanErr,   setScanErr]   = useState('')

  const isHF     = HF_TRANSPORTS.includes(transport)
  const isSerial = transport === 'serial' || transport === 'hf_serial'

  const connect = async () => {
    setLoading(true); setErr('')
    try {
      await droneControlApi.connect({
        drone_instance_id: droneId,
        transport,
        host,
        port,
        serial_port: serialPort,
        baud_rate: baud,
        hf_modem_type: isHF ? modemType : 'generic',
      })
      subscribe(droneId)
      await fetchConnections()
      onClose()
    } catch (e: any) {
      setErr(e.response?.data?.detail ?? 'Connection failed')
    } finally {
      setLoading(false)
    }
  }

  const scanPorts = async () => {
    setScanning(true); setScanErr(''); setPortList(null)
    try {
      const res = await droneControlApi.ports()
      setPortList(res.data)
    } catch (e: any) {
      setScanErr(e.response?.data?.detail ?? 'Port scan failed')
    } finally {
      setScanning(false)
    }
  }

  useEffect(() => { scanPorts() }, [])

  // Auto-fill form fields from a discovered port
  const applyPort = (p: PortInfo) => {
    if (p.type === 'serial' || p.type === 'usb') {
      setTransport('serial')
      setSerialPort(p.port)
      if (p.baud) setBaud(p.baud)
    } else if (p.type === 'udp') {
      setTransport('udp')
      // port string is like "udp:0.0.0.0:14550"
      const parts = p.port.split(':')
      if (parts.length === 3) { setHost(parts[1] || '0.0.0.0'); setPort(Number(parts[2])) }
    } else {
      // tcp
      setTransport('tcp')
      const parts = p.port.split(':')
      if (parts.length === 3) { setHost(parts[1]); setPort(Number(parts[2])) }
    }
  }

  // Group port list by type (manual groupBy — Object.groupBy is ES2024)
  const grouped: Record<string, PortInfo[]> | null = portList
    ? portList.reduce<Record<string, PortInfo[]>>((acc, p) => {
        ;(acc[p.type] ??= []).push(p)
        return acc
      }, {})
    : null

  const TYPE_LABELS: Record<string, string> = {
    serial: 'Serial', usb: 'USB-Serial', udp: 'UDP', tcp: 'TCP',
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.7)' }} onClick={onClose}>
      <div className="da-card w-full max-w-md p-6" onClick={e => e.stopPropagation()}
        style={{ maxHeight: '90vh', overflowY: 'auto' }}>

        <div className="flex items-center justify-between mb-5">
          <h3 className="font-semibold">Connect Drone</h3>
          <button onClick={onClose}><X size={16} style={{ color: '#6b7280' }} /></button>
        </div>

        {/* SITL quick-connect presets */}
        <div className="flex gap-2 mb-4 flex-wrap">
          <span className="text-[10px] self-center shrink-0" style={{ color: '#4b5563' }}>SITL PRESET:</span>
          <button
            className="text-[10px] px-2 py-1 rounded"
            style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.25)' }}
            onClick={() => { setTransport('udp'); setHost('0.0.0.0'); setPort(14550) }}>
            UDP 14550
          </button>
          <button
            className="text-[10px] px-2 py-1 rounded"
            style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6', border: '1px solid rgba(59,130,246,0.25)' }}
            onClick={() => { setTransport('tcp'); setHost('host.docker.internal'); setPort(5760) }}>
            TCP 5760
          </button>
        </div>

        {/* ── Port scanner ──────────────────────────────────────── */}
        <div className="mb-4 rounded"
          style={{ border: '1px solid var(--da-border)', background: 'rgba(255,255,255,0.02)' }}>
          <div className="flex items-center justify-between px-3 py-2"
            style={{ borderBottom: portList || scanErr ? '1px solid var(--da-border)' : 'none' }}>
            <span className="text-xs font-medium" style={{ color: '#64748b' }}>
              Discovered Ports
            </span>
            <button
              onClick={scanPorts}
              disabled={scanning}
              className="da-btn text-[10px] px-2 py-1 flex items-center gap-1.5"
              style={{
                background: 'rgba(32,208,180,0.08)',
                color: scanning ? '#4b5563' : 'var(--da-teal)',
                border: '1px solid rgba(32,208,180,0.25)',
              }}>
              <ScanLine size={11} className={scanning ? 'animate-pulse' : ''} />
              {scanning ? 'Scanning…' : 'Scan Ports'}
            </button>
          </div>

          {scanErr && (
            <p className="text-[11px] px-3 py-2" style={{ color: '#f87171' }}>{scanErr}</p>
          )}

          {portList && portList.length === 0 && (
            <p className="text-[11px] px-3 py-2" style={{ color: '#4b5563' }}>
              No ports found. Connect hardware and retry.
            </p>
          )}

          {grouped && Object.keys(grouped).map(type => (
            <div key={type}>
              <div className="px-3 py-1"
                style={{ background: 'rgba(255,255,255,0.02)', borderBottom: '1px solid var(--da-border)' }}>
                <span className="text-[9px] font-semibold tracking-widest mono"
                  style={{ color: '#374151' }}>
                  {TYPE_LABELS[type] ?? type.toUpperCase()}
                </span>
              </div>
              {(grouped[type] ?? []).map((p, i) => (
                <button key={i}
                  onClick={() => applyPort(p)}
                  className="w-full flex items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-white/5"
                  style={{ borderBottom: '1px solid var(--da-border)' }}>
                  <PortTypeIcon type={p.type} />
                  <div className="flex-1 min-w-0">
                    <div className="mono text-[11px] truncate" style={{ color: '#94a3b8' }}>
                      {p.port}
                    </div>
                    <div className="text-[10px] truncate" style={{ color: '#4b5563' }}>
                      {p.desc}
                      {p.baud ? ` · ${p.baud} baud` : ''}
                    </div>
                  </div>
                  <span className="text-[9px] shrink-0" style={{ color: 'var(--da-teal)' }}>
                    Use →
                  </span>
                </button>
              ))}
            </div>
          ))}
        </div>

        {/* ── Manual connection fields ──────────────────────────── */}
        <div className="flex flex-col gap-3">
          {/* Drone picker */}
          <label className="flex flex-col gap-1">
            <span className="text-xs" style={{ color: '#94a3b8' }}>DRONE</span>
            <select className="da-input" value={droneId}
              onChange={e => setDroneId(Number(e.target.value))}>
              {instances.map(d => (
                <option key={d.id} value={d.id}>{d.call_sign} (#{d.id})</option>
              ))}
            </select>
          </label>

          {/* Transport */}
          <label className="flex flex-col gap-1">
            <span className="text-xs" style={{ color: '#94a3b8' }}>TRANSPORT</span>
            <select className="da-input" value={transport}
              onChange={e => setTransport(e.target.value as Transport)}>
              <optgroup label="Standard">
                <option value="udp">UDP</option>
                <option value="tcp">TCP</option>
                <option value="serial">Serial</option>
              </optgroup>
              <optgroup label="HF Radio (Naval)">
                <option value="hf_serial">HF Serial (modem as serial port)</option>
                <option value="hf_tcp">HF TCP (modem ALE interface)</option>
              </optgroup>
            </select>
          </label>

          {/* HF modem type — only shown for HF transports */}
          {isHF && (
            <div className="flex flex-col gap-2 p-3 rounded"
              style={{ background: 'rgba(6,182,212,0.07)', border: '1px solid rgba(6,182,212,0.2)' }}>
              <div className="flex items-center gap-2 mb-1">
                <Radio size={13} style={{ color: '#06b6d4' }} />
                <span className="text-xs font-medium" style={{ color: '#06b6d4' }}>HF Link Configuration</span>
              </div>
              <label className="flex flex-col gap-1">
                <span className="text-xs" style={{ color: '#94a3b8' }}>MODEM TYPE</span>
                <select className="da-input" value={modemType}
                  onChange={e => setModemType(e.target.value as ModemType)}>
                  <option value="generic">Generic</option>
                  <option value="harris">Harris (AN/PRC series)</option>
                  <option value="codan">Codan</option>
                  <option value="barrett">Barrett</option>
                </select>
              </label>
              <p className="text-[11px]" style={{ color: '#4b5563' }}>
                HF uses extended timeouts (45 s heartbeat, 8 s ACK) and
                rate-limits telemetry to 1–2 Hz to stay within link bandwidth.
              </p>
            </div>
          )}

          {/* Serial port fields */}
          {isSerial ? (
            <div className="grid grid-cols-2 gap-3">
              <label className="flex flex-col gap-1">
                <span className="text-xs" style={{ color: '#94a3b8' }}>SERIAL PORT</span>
                <input className="da-input mono" value={serialPort}
                  onChange={e => setSerialPort(e.target.value)} />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs" style={{ color: '#94a3b8' }}>BAUD RATE</span>
                <input type="number" className="da-input mono" value={baud}
                  onChange={e => setBaud(Number(e.target.value))} />
              </label>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <label className="flex flex-col gap-1">
                <span className="text-xs" style={{ color: '#94a3b8' }}>HOST</span>
                <input className="da-input mono" value={host}
                  onChange={e => setHost(e.target.value)} />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs" style={{ color: '#94a3b8' }}>PORT</span>
                <input type="number" className="da-input mono" value={port}
                  onChange={e => setPort(Number(e.target.value))} />
              </label>
            </div>
          )}

          {err && (
            <p className="text-xs px-3 py-2 rounded"
              style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>{err}</p>
          )}

          <div className="flex gap-2 mt-2">
            <button className="da-btn da-btn-ghost flex-1" onClick={onClose}>Cancel</button>
            <button className="da-btn da-btn-primary flex-1" onClick={connect} disabled={loading}>
              {loading ? 'Connecting…' : 'Connect'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
