// ═══════════════════════════════════════════════════════════════
// src/workspaces/Fly/ManualControlPanel.tsx
// D-pad + WASD keyboard manual flight control
// ═══════════════════════════════════════════════════════════════
import { useCallback, useEffect, useRef, useState } from 'react'
import { droneControlApi } from '@/api/droneControl'

interface Props { droneId: number }

// key → [vx, vy, vz]  (NED frame: +x=north/forward, +y=east/right, +z=down)
const KEY_VEL: Record<string, [number, number, number]> = {
  w: [3, 0, 0],  arrowup:    [3, 0, 0],
  s: [-3, 0, 0], arrowdown:  [-3, 0, 0],
  a: [0, -3, 0], arrowleft:  [0, -3, 0],
  d: [0,  3, 0], arrowright: [0,  3, 0],
  r: [0, 0, -2],   // ascend  (vz negative = up in NED)
  f: [0, 0,  2],   // descend
}

const SEND_INTERVAL_MS = 100
const NUDGE_DURATION_MS = 800

export default function ManualControlPanel({ droneId }: Props) {
  const [kbEnabled, setKbEnabled] = useState(false)
  // Which keys are currently depressed (for visual highlight only)
  const [activeKeys, setActiveKeys] = useState<Set<string>>(new Set())

  // Refs — updated without triggering re-renders
  const velRef     = useRef<[number, number, number]>([0, 0, 0])
  const loopRef    = useRef<ReturnType<typeof setInterval> | null>(null)
  const heldKeysRef = useRef<Set<string>>(new Set())
  const busyRef    = useRef(false)

  // ── velocity sender ───────────────────────────────────────────
  const sendVel = useCallback(async (vx: number, vy: number, vz: number) => {
    if (busyRef.current) return
    busyRef.current = true
    try {
      await droneControlApi.velocity(droneId, vx, vy, vz)
    } catch { /* ignore — drone may be offline */ }
    finally { busyRef.current = false }
  }, [droneId])

  const stopLoop = useCallback(() => {
    if (!loopRef.current) return
    clearInterval(loopRef.current)
    loopRef.current = null
  }, [])

  const startLoop = useCallback(() => {
    if (loopRef.current) return
    loopRef.current = setInterval(() => {
      const [vx, vy, vz] = velRef.current
      if (vx === 0 && vy === 0 && vz === 0) { stopLoop(); return }
      sendVel(vx, vy, vz)
    }, SEND_INTERVAL_MS)
  }, [sendVel, stopLoop])

  // ── nudge (one-shot button press) ────────────────────────────
  const nudge = useCallback((vx: number, vy: number, vz: number) => {
    sendVel(vx, vy, vz)
    setTimeout(() => sendVel(0, 0, 0), NUDGE_DURATION_MS)
  }, [sendVel])

  // ── keyboard listeners ────────────────────────────────────────
  useEffect(() => {
    if (!kbEnabled) {
      stopLoop()
      velRef.current = [0, 0, 0]
      heldKeysRef.current.clear()
      setActiveKeys(new Set())
      return
    }

    const recompute = () => {
      let vx = 0, vy = 0, vz = 0
      heldKeysRef.current.forEach(k => {
        const v = KEY_VEL[k]
        if (v) { vx += v[0]; vy += v[1]; vz += v[2] }
      })
      velRef.current = [vx, vy, vz]
      setActiveKeys(new Set(heldKeysRef.current))
      if (vx || vy || vz) startLoop()
      else { stopLoop(); sendVel(0, 0, 0) }
    }

    const onDown = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase()
      if (KEY_VEL[k]) { e.preventDefault(); heldKeysRef.current.add(k); recompute() }
      if (k === ' ')  { e.preventDefault(); stopLoop(); sendVel(0, 0, 0) }
    }
    const onUp = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase()
      if (heldKeysRef.current.has(k)) { heldKeysRef.current.delete(k); recompute() }
    }

    window.addEventListener('keydown', onDown)
    window.addEventListener('keyup',   onUp)
    return () => {
      window.removeEventListener('keydown', onDown)
      window.removeEventListener('keyup',   onUp)
      stopLoop()
      velRef.current = [0, 0, 0]
      heldKeysRef.current.clear()
      sendVel(0, 0, 0)
    }
  }, [kbEnabled, startLoop, stopLoop, sendVel])

  // ── helpers for button active-state ──────────────────────────
  const isActive = (...keys: string[]) => keys.some(k => activeKeys.has(k))

  return (
    <div
      className="da-card flex flex-col gap-3 p-3"
      style={{ background: 'rgba(17,24,39,0.94)', backdropFilter: 'blur(10px)', minWidth: 188 }}>

      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="display font-semibold text-xs tracking-widest" style={{ color: '#4b5563' }}>
          MANUAL CONTROL
        </p>
        <label
          className="flex items-center gap-1.5 cursor-pointer select-none"
          title="Enable WASD / arrow-key control">
          <input
            type="checkbox"
            checked={kbEnabled}
            onChange={e => setKbEnabled(e.target.checked)}
            className="w-3 h-3 accent-blue-500" />
          <span
            className="mono text-[9px] font-semibold tracking-widest"
            style={{ color: kbEnabled ? '#3b82f6' : '#374151' }}>
            WASD
          </span>
        </label>
      </div>

      {/* ── 3×3 direction pad ── */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gridTemplateRows: 'repeat(3, 36px)',
        gap: 4,
      }}>
        {/* Row 1 */}
        <div />
        <Btn label="↑" hint="Forward (W / ↑)"
          active={isActive('w', 'arrowup')}
          onPress={() => nudge(3, 0, 0)} />
        <Btn label="⬆" hint="Ascend (R)" color="#22c55e"
          active={isActive('r')}
          onPress={() => nudge(0, 0, -2)} />

        {/* Row 2 */}
        <Btn label="←" hint="Strafe left (A / ←)"
          active={isActive('a', 'arrowleft')}
          onPress={() => nudge(0, -3, 0)} />
        <Btn label="■" hint="Stop (Space)" color="#f59e0b" active={false}
          onPress={() => { stopLoop(); sendVel(0, 0, 0) }} />
        <Btn label="→" hint="Strafe right (D / →)"
          active={isActive('d', 'arrowright')}
          onPress={() => nudge(0, 3, 0)} />

        {/* Row 3 */}
        <div />
        <Btn label="↓" hint="Back (S / ↓)"
          active={isActive('s', 'arrowdown')}
          onPress={() => nudge(-3, 0, 0)} />
        <Btn label="⬇" hint="Descend (F)" color="#ef4444"
          active={isActive('f')}
          onPress={() => nudge(0, 0, 2)} />
      </div>

      {/* Keyboard hint */}
      {kbEnabled ? (
        <p className="mono text-[9px] text-center" style={{ color: '#374151', letterSpacing: '0.05em' }}>
          W A S D · R/F alt · SPACE stop
        </p>
      ) : (
        <p className="text-[9px] text-center" style={{ color: '#1f2937' }}>
          Buttons send 0.8 s velocity bursts
        </p>
      )}
    </div>
  )
}

// ── tiny direction-pad button ─────────────────────────────────
function Btn({ label, hint, active, color = '#94a3b8', onPress }: {
  label: string
  hint: string
  active: boolean
  color?: string
  onPress: () => void
}) {
  return (
    <button
      onMouseDown={onPress}
      title={hint}
      className="flex items-center justify-center rounded font-bold select-none"
      style={{
        fontSize: 14,
        background: active ? `${color}1e` : 'rgba(255,255,255,0.03)',
        border: `1px solid ${active ? color : 'var(--da-border)'}`,
        color: active ? color : '#4b5563',
        transform: active ? 'scale(0.93)' : 'scale(1)',
        transition: 'all 0.07s',
      }}>
      {label}
    </button>
  )
}
