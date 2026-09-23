// ═══════════════════════════════════════════════════════════════
// src/components/common/CameraWindow.tsx
// Floating, draggable, resizable payload camera overlay.
// "0" (/ "1", ...) opens the operator's own browser webcam via getUserMedia;
// an IP/RTSP/HTTP stream URL is decoded server-side via OpenCV instead.
// ═══════════════════════════════════════════════════════════════
import { useCallback, useEffect, useRef, useState } from 'react'
import { Video, VideoOff, Volume2, VolumeX, X, GripHorizontal, RefreshCw, Lock } from 'lucide-react'
import { makeCameraStreamWS } from '../../api/client'

const DEFAULT_TOP       = 110    // px from top of viewport
const DEFAULT_RIGHT     = 20     // px from right
const DEFAULT_W         = 320
const DEFAULT_H         = 230

interface Props {
  visible: boolean
  onClose: () => void
}

type FeedState = 'idle' | 'connecting' | 'live' | 'error'
type VisionMode = 'day' | 'night'

export function CameraWindow({ visible, onClose }: Props) {
  const winRef    = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const videoRef  = useRef<HTMLVideoElement>(null)
  const wsRef     = useRef<WebSocket | null>(null)
  const localStreamRef = useRef<MediaStream | null>(null)

  const [inputUrl, setInputUrl] = useState('')
  const [liveSource, setLiveSource] = useState('')
  const [feedState, setFeedState] = useState<FeedState>('idle')
  const [isLocalWebcam, setIsLocalWebcam] = useState(false)
  const [muted,    setMuted]    = useState(true)
  const [errorMsg, setErrorMsg] = useState('')
  const [visionMode, setVisionMode] = useState<VisionMode>('day')

  // ── freeze / draw-box ────────────────────────────────────────────
  // "L" freezes the feed on its current picture; "U" resumes it. While
  // frozen, clicking the (now-still) picture draws a box around whatever
  // point was clicked — purely client-side, since the picture isn't moving
  // there's nothing to track, just a marker on a held frame.
  //   - Local webcam: the frame is snapshotted onto the canvas (a <video>
  //     can't have shapes drawn on it), which then takes over as the
  //     visible element until resumed.
  //   - Remote (backend/OpenCV) feed: stop drawing incoming WS frames onto
  //     the canvas, holding whatever was last drawn, and draw boxes
  //     directly onto that same canvas.
  const [locked, setLocked] = useState(false)
  const feedStateRef = useRef(feedState)
  const isLocalWebcamRef = useRef(isLocalWebcam)
  const lockedRef = useRef(false)
  useEffect(() => { feedStateRef.current = feedState }, [feedState])
  useEffect(() => { isLocalWebcamRef.current = isLocalWebcam }, [isLocalWebcam])
  useEffect(() => { lockedRef.current = locked }, [locked])

  // ── zoom (of the drawn box itself) ──────────────────────────────
  // "+" grows the last-drawn box (zoom in on the boxed object), "-" shrinks
  // it (zoom out) — not a zoom of the picture. The base frozen frame is
  // kept separately (frozenFrameRef) so the box can be redrawn at a new
  // size on the *same* pixels each time, instead of drawing on top of the
  // previous box outline or needing to re-snapshot the source.
  const frozenFrameRef = useRef<ImageBitmap | null>(null)
  const boxRef = useRef<{ cx: number; cy: number; halfW: number; halfH: number; name: string } | null>(null)

  const BOX_HALF_SIZE = 45   // px, in raw canvas/frame pixel coordinates
  const BOX_MIN_HALF_SIZE = 12
  const BOX_MAX_HALF_SIZE = 400
  const BOX_ZOOM_STEP = 1.25

  // ── name the boxed object ─────────────────────────────────────────
  // "N" opens a text input to name the current box (only if it has none
  // yet); "E" opens the same input pre-filled to edit an existing name.
  // Enter commits, Escape cancels. The name is drawn onto the canvas as a
  // label above the box once committed (see drawBox below).
  const [namingOpen, setNamingOpen] = useState(false)
  const [nameDraft, setNameDraft] = useState('')
  const nameInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (namingOpen) nameInputRef.current?.focus()
  }, [namingOpen])

  const sendCmd = (cmd: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(cmd))
    }
  }

  const redrawFrozenFrame = useCallback(() => {
    const canvas = canvasRef.current
    const base = frozenFrameRef.current
    if (!canvas || !base) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(base, 0, 0, canvas.width, canvas.height)
  }, [])

  const drawBox = useCallback(() => {
    const canvas = canvasRef.current
    const box = boxRef.current
    if (!canvas || !box) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const { cx, cy, halfW, halfH, name } = box
    const lineScale = canvas.width / (canvas.getBoundingClientRect().width || canvas.width)
    ctx.save()
    ctx.strokeStyle = '#f59e0b'
    ctx.lineWidth = Math.max(2, 2 * lineScale)
    ctx.strokeRect(cx - halfW, cy - halfH, halfW * 2, halfH * 2)
    const armLen = Math.min(halfW, halfH) * 0.3
    ctx.beginPath()
    ctx.moveTo(cx - armLen, cy); ctx.lineTo(cx + armLen, cy)
    ctx.moveTo(cx, cy - armLen); ctx.lineTo(cx, cy + armLen)
    ctx.stroke()

    if (name) {
      const fontSize = Math.max(11, 12 * lineScale)
      ctx.font = `600 ${fontSize}px sans-serif`
      const textW = ctx.measureText(name).width
      const padX = 4 * lineScale, padY = 3 * lineScale
      const labelX = cx - halfW
      const labelY = cy - halfH - fontSize - padY * 2 - 2 * lineScale
      ctx.fillStyle = 'rgba(245,158,11,0.92)'
      ctx.fillRect(labelX, labelY, textW + padX * 2, fontSize + padY * 2)
      ctx.fillStyle = '#0a0a0a'
      ctx.textBaseline = 'top'
      ctx.fillText(name, labelX + padX, labelY + padY)
    }
    ctx.restore()
  }, [])

  const redrawWithBox = useCallback(() => {
    redrawFrozenFrame()
    drawBox()
  }, [redrawFrozenFrame, drawBox])

  const openNaming = useCallback((prefill: string) => {
    if (!lockedRef.current || !boxRef.current) return
    setNameDraft(prefill)
    setNamingOpen(true)
  }, [])

  const commitName = useCallback(() => {
    if (boxRef.current) {
      boxRef.current = { ...boxRef.current, name: nameDraft.trim() }
      redrawWithBox()
    }
    setNamingOpen(false)
  }, [nameDraft, redrawWithBox])

  const cancelNaming = useCallback(() => {
    setNamingOpen(false)
  }, [])

  const drawBoxAt = useCallback((clientX: number, clientY: number) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    // canvas.width/height are the raw frame's pixel size, which can differ
    // from its displayed (object-cover) CSS size — scale accordingly so the
    // box lands under the cursor regardless of window size.
    const scaleX = canvas.width  / rect.width
    const scaleY = canvas.height / rect.height
    const cx = (clientX - rect.left) * scaleX
    const cy = (clientY - rect.top)  * scaleY

    boxRef.current = { cx, cy, halfW: BOX_HALF_SIZE * scaleX, halfH: BOX_HALF_SIZE * scaleY, name: '' }
    setNameDraft('')
    setNamingOpen(false)
    redrawWithBox()
  }, [redrawWithBox])

  const zoomBox = useCallback((factor: number) => {
    const box = boxRef.current
    if (!box) return   // nothing boxed yet — +/- has nothing to act on
    const halfW = Math.min(BOX_MAX_HALF_SIZE, Math.max(BOX_MIN_HALF_SIZE, box.halfW * factor))
    const halfH = Math.min(BOX_MAX_HALF_SIZE, Math.max(BOX_MIN_HALF_SIZE, box.halfH * factor))
    boxRef.current = { ...box, halfW, halfH }
    redrawWithBox()
  }, [redrawWithBox])

  const zoomIn  = useCallback(() => zoomBox(BOX_ZOOM_STEP), [zoomBox])
  const zoomOut = useCallback(() => zoomBox(1 / BOX_ZOOM_STEP), [zoomBox])

  const freeze = useCallback(async () => {
    if (feedStateRef.current !== 'live') return
    const canvas = canvasRef.current
    const video = videoRef.current
    boxRef.current = null   // start each freeze with no box yet
    setNamingOpen(false)

    if (isLocalWebcamRef.current && video && canvas) {
      // Snapshot the current video frame onto the canvas, then show the
      // canvas in place of the <video> so clicks can draw boxes on it.
      canvas.width  = video.videoWidth  || canvas.clientWidth
      canvas.height = video.videoHeight || canvas.clientHeight
      canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height)
      video.pause()
    }
    // Keep a copy of the just-frozen picture (both paths: local webcam
    // snapshot above, or the remote feed's last-drawn WS frame already on
    // the canvas) so zoomBox() can redraw the box at a new size on top of
    // clean pixels instead of on top of the previous box outline.
    if (canvas && canvas.width > 0 && canvas.height > 0) {
      try {
        frozenFrameRef.current = await createImageBitmap(canvas)
      } catch {
        frozenFrameRef.current = null   // best-effort — zoom just won't be available
      }
    }
    setLocked(true)
  }, [])

  const resume = useCallback(() => {
    if (isLocalWebcamRef.current) {
      videoRef.current?.play().catch(() => {})
    } else {
      sendCmd({ cmd: 'unlock' })
    }
    frozenFrameRef.current = null
    boxRef.current = null
    setNamingOpen(false)
    setLocked(false)
  }, [])

  const onFeedClick = useCallback((e: React.MouseEvent<HTMLElement>) => {
    if (feedStateRef.current !== 'live') return
    if (lockedRef.current) {
      drawBoxAt(e.clientX, e.clientY)
    } else {
      freeze()
    }
  }, [freeze, drawBoxAt])

  // "I" toggles day/night vision. "L" freezes the feed on its current
  // picture; "U" resumes it. While frozen and a box has been drawn, "+"
  // grows the box (zoom in) and "-" shrinks it (zoom out). "N" opens a
  // naming input for a fresh (unnamed) box; "E" opens the same input to
  // edit whatever name the box already has.
  useEffect(() => {
    if (!visible) return
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return
      const key = e.key === '=' ? '+' : e.key   // "+" is often shift+"=" with no separate keycode
      const lower = key.toLowerCase()
      if (!['l', 'u', 'i', '+', '-', 'n', 'e'].includes(lower)) return

      if (lower === 'i') {
        setVisionMode(m => (m === 'day' ? 'night' : 'day'))
        return
      }
      if (feedStateRef.current !== 'live') return

      if (lower === 'l') {
        if (!lockedRef.current) freeze()
      } else if (lower === 'u') {
        if (lockedRef.current) resume()
      } else if (lower === '+') {
        if (lockedRef.current) zoomIn()
      } else if (lower === '-') {
        if (lockedRef.current) zoomOut()
      } else if (lower === 'n') {
        openNaming('')
      } else if (lower === 'e') {
        openNaming(boxRef.current?.name ?? '')
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [visible, freeze, resume, zoomIn, zoomOut, openNaming])

  const visionFilter = visionMode === 'night'
    ? 'brightness(1.35) contrast(1.2) saturate(1.6) hue-rotate(70deg) sepia(0.25)'
    : 'brightness(1.15) contrast(1.02) saturate(1)'

  // ── dragging ──────────────────────────────────────────────────
  const dragOrigin = useRef<{ mx: number; my: number; left: number; top: number } | null>(null)

  const onDragStart = useCallback((e: React.MouseEvent) => {
    if (!winRef.current) return
    e.preventDefault()
    const rect = winRef.current.getBoundingClientRect()
    dragOrigin.current = { mx: e.clientX, my: e.clientY, left: rect.left, top: rect.top }

    const onMove = (me: MouseEvent) => {
      if (!dragOrigin.current || !winRef.current) return
      const rect2 = winRef.current.getBoundingClientRect()
      const dx = me.clientX - dragOrigin.current.mx
      const dy = me.clientY - dragOrigin.current.my
      const maxL = window.innerWidth  - rect2.width  - 8
      const maxT = window.innerHeight - rect2.height - 8
      const nl = Math.max(8, Math.min(maxL, dragOrigin.current.left + dx))
      const nt = Math.max(44, Math.min(maxT, dragOrigin.current.top  + dy))
      winRef.current.style.left  = `${nl}px`
      winRef.current.style.top   = `${nt}px`
      winRef.current.style.right = 'auto'
    }
    const onUp = () => {
      dragOrigin.current = null
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup',   onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup',   onUp)
  }, [])

  // ── connect / stream (OpenCV via WebSocket) ─────────────────────
  const firstFrameTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearFirstFrameTimer = () => {
    if (firstFrameTimer.current) {
      clearTimeout(firstFrameTimer.current)
      firstFrameTimer.current = null
    }
  }

  const teardownSocket = () => {
    clearFirstFrameTimer()
    if (wsRef.current) {
      wsRef.current.onopen = null
      wsRef.current.onmessage = null
      wsRef.current.onerror = null
      wsRef.current.onclose = null
      wsRef.current.close()
      wsRef.current = null
    }
  }

  const teardownLocalWebcam = () => {
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach(t => t.stop())
      localStreamRef.current = null
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
  }

  // Bare "0", "1", ... opens the operator's own browser webcam via
  // getUserMedia; anything else (IP / RTSP / HTTP / MJPEG URL) is
  // decoded server-side via OpenCV.
  const connectLocalWebcam = async (raw: string) => {
    setIsLocalWebcam(true)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
      localStreamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play()
      }
      setLiveSource(`local webcam (${raw})`)
      setFeedState('live')
    } catch (err) {
      setFeedState('error')
      setErrorMsg(
        err instanceof Error && err.name === 'NotAllowedError'
          ? 'Webcam access was denied. Allow camera permission for this site and try again.'
          : 'Could not access your local webcam. Make sure it is connected and not in use by another app.'
      )
      teardownLocalWebcam()
    }
  }

  const connect = () => {
    const raw = inputUrl.trim()
    if (!raw) return

    setErrorMsg('')
    setFeedState('connecting')
    teardownSocket()
    teardownLocalWebcam()

    if (/^\d+$/.test(raw)) {
      setIsLocalWebcam(true)
      connectLocalWebcam(raw)
      return
    }
    setIsLocalWebcam(false)

    const source = raw
    let gotFirstFrame = false

    const ws = makeCameraStreamWS(source)
    wsRef.current = ws

    ws.onopen = () => {
      // Connection accepted, but the source may still fail to open on the
      // backend (bad IP, unreachable RTSP, no such webcam index) — that
      // failure never closes the socket, it just never sends a frame. A
      // bare IP is auto-probed against several candidate camera URLs
      // server-side (a few seconds each), so this must wait longer than a
      // single-attempt connect would need before giving up.
      firstFrameTimer.current = setTimeout(() => {
        if (!gotFirstFrame) {
          setFeedState('error')
          setErrorMsg(
            'Connected, but no video frame arrived. The source could not be opened on the server — ' +
            'check the IP/URL is reachable from the backend, or that webcam index actually exists there ' +
            '(note: "0" opens a webcam on the backend host/container, not on your browser\'s machine).'
          )
          teardownSocket()
        }
      }, 16000)
    }

    ws.onmessage = ev => {
      const canvas = canvasRef.current
      if (!canvas || !(ev.data instanceof ArrayBuffer)) return
      if (!gotFirstFrame) {
        gotFirstFrame = true
        clearFirstFrameTimer()
        setLiveSource(source)
        setFeedState('live')
      }
      // Locked → freeze on the current picture; stop drawing incoming
      // frames (the server keeps sending them with the tracking box
      // burned in, but the displayed image itself holds still until
      // unlocked). Unlocked → live, draw every frame as it arrives.
      if (lockedRef.current) return
      const blob = new Blob([ev.data], { type: 'image/jpeg' })
      const bitmapUrl = URL.createObjectURL(blob)
      const img = new Image()
      img.onload = () => {
        if (canvas.width !== img.width || canvas.height !== img.height) {
          canvas.width = img.width
          canvas.height = img.height
        }
        canvas.getContext('2d')?.drawImage(img, 0, 0)
        URL.revokeObjectURL(bitmapUrl)
      }
      img.src = bitmapUrl
    }

    ws.onerror = () => {
      setFeedState('error')
      setErrorMsg('Could not reach camera. Check the IP/URL, or that webcam index is available on the server.')
    }

    ws.onclose = () => {
      setFeedState(prev => (prev === 'live' || prev === 'connecting' ? 'error' : prev))
      setErrorMsg(prev => prev || 'Feed disconnected.')
    }
  }

  const disconnect = () => {
    teardownSocket()
    teardownLocalWebcam()
    setIsLocalWebcam(false)
    setLiveSource('')
    setFeedState('idle')
    setErrorMsg('')
    setLocked(false)
    setNamingOpen(false)
    frozenFrameRef.current = null
    boxRef.current = null
    const ctx = canvasRef.current?.getContext('2d')
    if (ctx && canvasRef.current) ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height)
  }

  useEffect(() => () => { teardownSocket(); teardownLocalWebcam() }, [])

  // Re-clamp position if window is resized
  useEffect(() => {
    const handler = () => {
      if (!winRef.current) return
      const rect = winRef.current.getBoundingClientRect()
      if (rect.right > window.innerWidth) {
        winRef.current.style.left  = `${Math.max(8, window.innerWidth - rect.width - 8)}px`
        winRef.current.style.right = 'auto'
      }
    }
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [])

  if (!visible) return null

  const borderColor = feedState === 'live'
    ? 'rgba(34,197,94,0.4)'
    : feedState === 'error'
    ? 'rgba(239,68,68,0.4)'
    : 'var(--da-border)'

  return (
    <div
      ref={winRef}
      style={{
        position: 'fixed',
        top: DEFAULT_TOP,
        right: DEFAULT_RIGHT,
        width: DEFAULT_W,
        minWidth: 220,
        minHeight: 160,
        zIndex: 1900,
        display: 'flex',
        flexDirection: 'column',
        border: `1px solid ${borderColor}`,
        borderRadius: 8,
        background: 'rgba(6,12,21,0.97)',
        boxShadow: '0 20px 48px rgba(0,0,0,0.55)',
        resize: 'both',
        overflow: 'hidden',
        transition: 'border-color 0.2s',
      }}>

      {/* ── Header / drag handle ── */}
      <div
        onMouseDown={onDragStart}
        className="flex items-center justify-between gap-2 px-3 py-2 cursor-move select-none shrink-0"
        style={{
          background: feedState === 'live'
            ? 'rgba(34,197,94,0.07)'
            : 'rgba(59,130,246,0.06)',
          borderBottom: '1px solid var(--da-border)',
        }}>

        <div className="flex items-center gap-2 min-w-0">
          <GripHorizontal size={12} style={{ color: '#374151', flexShrink: 0 }} />
          <Video size={12} style={{
            color: feedState === 'live' ? '#22c55e' : '#6b7280',
            flexShrink: 0,
          }} />
          <span className="display font-semibold text-xs truncate" style={{ color: '#94a3b8' }}>
            Payload Camera
          </span>
          {feedState === 'live' && (
            <span className="da-chip ok shrink-0 py-0.5 px-1.5" style={{ fontSize: 8 }}>
              <span className="da-chip-dot" />LIVE
            </span>
          )}
          {locked && (
            <span
              className="flex items-center gap-0.5 shrink-0 py-0.5 px-1.5 rounded"
              style={{ fontSize: 8, background: 'rgba(245,158,11,0.15)', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.35)' }}>
              <Lock size={8} />FROZEN
            </span>
          )}
          {feedState === 'connecting' && (
            <RefreshCw size={10} className="animate-spin shrink-0" style={{ color: '#f59e0b' }} />
          )}
        </div>

        <div className="flex items-center gap-0.5 shrink-0">
          {/* Mute toggle */}
          <button
            onClick={() => setMuted(v => !v)}
            className="w-6 h-6 flex items-center justify-center rounded hover:bg-white/5 transition-colors"
            title={muted ? 'Unmute' : 'Mute'}>
            {muted
              ? <VolumeX size={11} style={{ color: '#4b5563' }} />
              : <Volume2 size={11} style={{ color: '#94a3b8' }} />}
          </button>

          {/* Disconnect */}
          {feedState === 'live' && (
            <button
              onClick={disconnect}
              className="w-6 h-6 flex items-center justify-center rounded hover:bg-white/5 transition-colors"
              title="Disconnect camera">
              <VideoOff size={11} style={{ color: '#4b5563' }} />
            </button>
          )}

          {/* Close */}
          <button
            onClick={onClose}
            className="w-6 h-6 flex items-center justify-center rounded hover:bg-white/5 transition-colors"
            title="Close camera window">
            <X size={11} style={{ color: '#6b7280' }} />
          </button>
        </div>
      </div>

      {/* ── Body ── */}
      <div className="flex-1 relative overflow-hidden" style={{ background: '#020609', minHeight: 0 }}>

        {/* Local webcam — captured directly in the browser via getUserMedia.
            Click to freeze (snapshots onto the canvas, which then takes
            over — see below). Stays mounted while frozen so its current
            frame remains available to snapshot, but hidden behind the
            canvas. */}
        <video
          ref={videoRef}
          onClick={onFeedClick}
          muted
          playsInline
          className="w-full h-full object-cover"
          style={{
            display: feedState === 'live' && isLocalWebcam && !locked ? 'block' : 'none',
            filter: visionFilter,
            transition: 'filter 0.25s',
            cursor: feedState === 'live' ? 'pointer' : 'default',
          }}
        />

        {/* Canvas: for a remote feed it's always the live render surface
            (frames decoded from OpenCV JPEGs); for local webcam it only
            takes over once frozen, holding the snapshotted frame so boxes
            can be drawn on it. Click to freeze, or (while frozen) to draw a
            box at that point; "L"/"U" freeze/resume. */}
        <canvas
          ref={canvasRef}
          onClick={onFeedClick}
          className="w-full h-full object-cover"
          style={{
            display: feedState === 'live' && (!isLocalWebcam || locked) ? 'block' : 'none',
            filter: visionFilter,
            transition: 'filter 0.25s',
            cursor: feedState === 'live' ? (locked ? 'crosshair' : 'pointer') : 'default',
          }}
        />

        {feedState === 'live' && (
          <span
            className="absolute top-1.5 left-1.5 px-1.5 py-0.5 rounded text-[9px] font-semibold tracking-wide"
            style={{
              background: visionMode === 'night' ? 'rgba(34,197,94,0.15)' : 'rgba(59,130,246,0.15)',
              color: visionMode === 'night' ? '#4ade80' : '#93c5fd',
              border: `1px solid ${visionMode === 'night' ? 'rgba(74,222,128,0.35)' : 'rgba(147,197,253,0.35)'}`,
            }}>
            {visionMode === 'night' ? 'NIGHT VISION' : 'DAY VISION'}
          </span>
        )}

        {/* Name/edit-name input — "N" (new) or "E" (edit) while a box is
            drawn. Enter commits (redraws the box with the label burned in),
            Escape cancels without changing the existing name. */}
        {namingOpen && (
          <div
            className="absolute left-1.5 right-1.5 bottom-1.5 flex items-center gap-1.5 px-2 py-1.5 rounded"
            style={{ background: 'rgba(6,12,21,0.95)', border: '1px solid rgba(245,158,11,0.4)' }}>
            <input
              ref={nameInputRef}
              className="da-input mono text-xs flex-1"
              placeholder="Object name…"
              value={nameDraft}
              maxLength={40}
              onChange={e => setNameDraft(e.target.value)}
              onKeyDown={e => {
                e.stopPropagation()   // don't let L/U/+/- etc. fire while typing
                if (e.key === 'Enter') commitName()
                else if (e.key === 'Escape') cancelNaming()
              }}
            />
            <button onClick={commitName} className="da-btn da-btn-primary text-xs px-2 shrink-0">
              Set
            </button>
          </div>
        )}

        {/* Idle / error — connect form */}
        {(feedState === 'idle' || feedState === 'error' || feedState === 'connecting') && (
          <div className="flex flex-col gap-3 p-3">

            {feedState === 'error' && (
              <p className="text-[10px] px-2 py-1.5 rounded"
                style={{ background: 'rgba(239,68,68,0.1)', color: '#f87171', border: '1px solid rgba(239,68,68,0.25)' }}>
                {errorMsg}
              </p>
            )}

            <p className="text-[10px]" style={{ color: '#4b5563' }}>
              Camera IP / stream URL, or "0" for your local webcam
            </p>

            <div className="flex gap-2">
              <input
                className="da-input mono text-xs flex-1"
                placeholder="0  or  192.168.1.100  or  rtsp://…"
                value={inputUrl}
                onChange={e => setInputUrl(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && connect()}
                disabled={feedState === 'connecting'}
              />
              <button
                onClick={connect}
                disabled={feedState === 'connecting' || !inputUrl.trim()}
                className="da-btn da-btn-primary text-xs px-3 shrink-0">
                {feedState === 'connecting' ? '…' : 'Connect'}
              </button>
            </div>

            <div style={{ color: '#1f2937', fontSize: 9, lineHeight: 1.6 }}>
              <p>Enter "0" (or 1, 2…) to open your browser's own webcam</p>
              <p>A bare IP (e.g. 192.168.1.100) auto-detects common mobile camera apps</p>
              <p>Full RTSP / HTTP / MJPEG URLs are also accepted and decoded server-side</p>
              <p>Press <b>I</b> to toggle day / night vision</p>
              <p>Press <b>L</b>, or click the feed, to freeze it. While frozen: click an object to box it, <b>+</b>/<b>-</b> to zoom the box, <b>N</b> to name it, <b>E</b> to edit its name — press <b>U</b> to resume.</p>
            </div>
          </div>
        )}
      </div>

      {/* ── Footer — resize hint ── */}
      <div className="px-3 py-1 shrink-0 flex items-center justify-between"
        style={{ borderTop: '1px solid var(--da-border)' }}>
        <span className="text-[9px] mono" style={{ color: '#1f2937' }}>
          {feedState === 'live' ? liveSource.slice(0, 40) : 'No feed'}
        </span>
        <span className="text-[8px]" style={{ color: '#1f2937' }}>drag · resize ↘</span>
      </div>
    </div>
  )
}

export default CameraWindow
