// ═══════════════════════════════════════════════════════════════
// src/components/common/CameraWindow.tsx
// Floating, draggable, resizable payload camera overlay.
// Supports MJPEG image streams, HLS/MP4 video, and MediaStream.
// ═══════════════════════════════════════════════════════════════
import { useCallback, useEffect, useRef, useState } from 'react'
import { Video, VideoOff, Volume2, VolumeX, X, GripHorizontal, RefreshCw } from 'lucide-react'

// Common MJPEG/stream paths probed when user enters a bare IP
const PROBE_PATHS = [
  '/video', '/video.mjpg', '/mjpeg', '/mjpegfeed',
  '/stream', '/live', '/axis-cgi/mjpg/video.cgi',
  '/cam/realmonitor?channel=1&subtype=0',
]

const PROBE_TIMEOUT_MS  = 3_000
const DEFAULT_TOP       = 110    // px from top of viewport
const DEFAULT_RIGHT     = 20     // px from right
const DEFAULT_W         = 320
const DEFAULT_H         = 230

interface Props {
  visible: boolean
  onClose: () => void
}

type FeedState = 'idle' | 'probing' | 'live' | 'error'

export function CameraWindow({ visible, onClose }: Props) {
  const winRef  = useRef<HTMLDivElement>(null)
  const imgRef  = useRef<HTMLImageElement>(null)
  const vidRef  = useRef<HTMLVideoElement>(null)

  const [inputUrl, setInputUrl] = useState('')
  const [liveUrl,  setLiveUrl]  = useState('')
  const [isVideo,  setIsVideo]  = useState(false)
  const [feedState, setFeedState] = useState<FeedState>('idle')
  const [muted,    setMuted]    = useState(true)
  const [errorMsg, setErrorMsg] = useState('')

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

  // ── connect ───────────────────────────────────────────────────
  const connect = async () => {
    const raw = inputUrl.trim()
    if (!raw) return

    setErrorMsg('')
    setFeedState('probing')

    const isExplicitUrl = /^https?:\/\//i.test(raw) || raw.includes('/')

    if (isExplicitUrl) {
      // Detect format from extension/path
      const isVid = /\.(m3u8|mp4|webm|ogg)/i.test(raw)
      setIsVideo(isVid)
      setLiveUrl(raw)
      setFeedState('live')
      return
    }

    // Bare IP — probe common MJPEG paths
    const host = raw.split(':')[0]
    const customPort = raw.includes(':') ? `:${raw.split(':')[1]}` : ''
    const bases = customPort
      ? [`http://${host}${customPort}`]
      : [`http://${host}`, `http://${host}:8080`, `http://${host}:81`]

    for (const base of bases) {
      for (const path of PROBE_PATHS) {
        const url = `${base}${path}`
        const found = await probeImage(url)
        if (found) {
          setIsVideo(false)
          setLiveUrl(url)
          setFeedState('live')
          return
        }
      }
    }

    setFeedState('error')
    setErrorMsg('Could not reach camera. Enter a full stream URL to connect manually.')
  }

  const disconnect = () => {
    setLiveUrl('')
    setIsVideo(false)
    setFeedState('idle')
    setErrorMsg('')
    if (vidRef.current) { vidRef.current.pause(); vidRef.current.src = '' }
  }

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
        zIndex: 900,
        display: 'flex',
        flexDirection: 'column',
        border: `1px solid ${borderColor}`,
        borderRadius: 14,
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
          {feedState === 'probing' && (
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

        {/* Live feed — image (MJPEG) */}
        {feedState === 'live' && !isVideo && (
          <img
            ref={imgRef}
            src={liveUrl}
            alt="Camera feed"
            className="w-full h-full object-cover"
            onError={() => { setFeedState('error'); setErrorMsg('Feed disconnected.') }}
          />
        )}

        {/* Live feed — video (HLS/MP4) */}
        {feedState === 'live' && isVideo && (
          <video
            ref={vidRef}
            src={liveUrl}
            autoPlay
            muted={muted}
            playsInline
            className="w-full h-full object-cover"
            onError={() => { setFeedState('error'); setErrorMsg('Video stream failed.') }}
          />
        )}

        {/* Idle / error — connect form */}
        {(feedState === 'idle' || feedState === 'error' || feedState === 'probing') && (
          <div className="flex flex-col gap-3 p-3">

            {feedState === 'error' && (
              <p className="text-[10px] px-2 py-1.5 rounded"
                style={{ background: 'rgba(239,68,68,0.1)', color: '#f87171', border: '1px solid rgba(239,68,68,0.25)' }}>
                {errorMsg}
              </p>
            )}

            <p className="text-[10px]" style={{ color: '#4b5563' }}>
              Camera IP address or full stream URL
            </p>

            <div className="flex gap-2">
              <input
                className="da-input mono text-xs flex-1"
                placeholder="192.168.1.100  or  http://…/stream"
                value={inputUrl}
                onChange={e => setInputUrl(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && connect()}
                disabled={feedState === 'probing'}
              />
              <button
                onClick={connect}
                disabled={feedState === 'probing' || !inputUrl.trim()}
                className="da-btn da-btn-primary text-xs px-3 shrink-0">
                {feedState === 'probing' ? '…' : 'Connect'}
              </button>
            </div>

            <div style={{ color: '#1f2937', fontSize: 9, lineHeight: 1.6 }}>
              <p>Supports MJPEG · HLS (.m3u8) · MP4</p>
              <p>Bare IP auto-probes common stream paths</p>
              <p style={{ marginTop: 2, color: '#374151' }}>
                Programmatic: <code>window.DACamera?.attach(MediaStream)</code>
              </p>
            </div>
          </div>
        )}
      </div>

      {/* ── Footer — resize hint ── */}
      <div className="px-3 py-1 shrink-0 flex items-center justify-between"
        style={{ borderTop: '1px solid var(--da-border)' }}>
        <span className="text-[9px] mono" style={{ color: '#1f2937' }}>
          {feedState === 'live' ? liveUrl.slice(0, 40) : 'No feed'}
        </span>
        <span className="text-[8px]" style={{ color: '#1f2937' }}>drag · resize ↘</span>
      </div>
    </div>
  )
}

// ── Probe a single MJPEG URL (resolves true if image loads within timeout) ──
function probeImage(url: string): Promise<boolean> {
  return new Promise(resolve => {
    const img   = new Image()
    const timer = setTimeout(() => { img.src = ''; resolve(false) }, PROBE_TIMEOUT_MS)
    img.onload  = () => { clearTimeout(timer); resolve(true)  }
    img.onerror = () => { clearTimeout(timer); resolve(false) }
    img.src = url
  })
}

export default CameraWindow
