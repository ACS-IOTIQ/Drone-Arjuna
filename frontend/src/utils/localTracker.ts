// ═══════════════════════════════════════════
// src/utils/localTracker.ts
// Lightweight in-browser object tracker for the LOCAL webcam, whose frames
// never reach the backend (remote feeds are tracked server-side by OpenCV).
//
// Method: template matching. The patch inside the operator's box is kept as a
// grayscale template; on every new frame we search a window around the last
// position for the offset with the smallest mean absolute difference (MAD).
// Everything runs on a downscaled grayscale copy, so a frame costs well under
// a millisecond-scale amount of work and is fine at ~15 fps.
// ═══════════════════════════════════════════

export interface Gray {
  data: Uint8ClampedArray | Uint8Array
  w: number
  h: number
}

export interface MatchResult {
  /** Top-left corner of the best match, in frame pixels. */
  x: number
  y: number
  /** Mean absolute grey-level difference (0 = identical, 255 = opposite). */
  mad: number
}

/** RGBA pixels (canvas ImageData) -> luma. */
export function toGray(rgba: Uint8ClampedArray, w: number, h: number): Gray {
  const out = new Uint8Array(w * h)
  for (let i = 0, p = 0; i < out.length; i++, p += 4) {
    out[i] = (rgba[p] * 77 + rgba[p + 1] * 150 + rgba[p + 2] * 29) >> 8
  }
  return { data: out, w, h }
}

/** Copy a rectangle out of a gray image (clamped to the image). */
export function cropGray(g: Gray, x0: number, y0: number, w: number, h: number): Gray {
  const x = Math.max(0, Math.min(g.w - 1, Math.round(x0)))
  const y = Math.max(0, Math.min(g.h - 1, Math.round(y0)))
  const cw = Math.max(1, Math.min(Math.round(w), g.w - x))
  const ch = Math.max(1, Math.min(Math.round(h), g.h - y))
  const out = new Uint8Array(cw * ch)
  for (let row = 0; row < ch; row++) {
    const src = (y + row) * g.w + x
    out.set(g.data.subarray(src, src + cw), row * cw)
  }
  return { data: out, w: cw, h: ch }
}

/**
 * Find where `tpl` best matches inside `frame`, searching offsets within
 * `radius` pixels of (`cx`, `cy`) — the previous top-left corner.
 * `step` subsamples the template (2 = every other pixel) to bound the cost.
 */
export function matchTemplate(
  frame: Gray, tpl: Gray, cx: number, cy: number, radius: number, step = 2,
): MatchResult {
  const maxX = frame.w - tpl.w
  const maxY = frame.h - tpl.h
  const x0 = Math.max(0, Math.round(cx - radius))
  const x1 = Math.min(maxX, Math.round(cx + radius))
  const y0 = Math.max(0, Math.round(cy - radius))
  const y1 = Math.min(maxY, Math.round(cy + radius))

  let best: MatchResult = { x: Math.max(0, Math.min(maxX, Math.round(cx))), y: Math.max(0, Math.min(maxY, Math.round(cy))), mad: 255 }
  if (maxX < 0 || maxY < 0) return best

  let samples = 0
  for (let ty = 0; ty < tpl.h; ty += step) for (let tx = 0; tx < tpl.w; tx += step) samples++

  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      let sum = 0
      for (let ty = 0; ty < tpl.h; ty += step) {
        const frow = (y + ty) * frame.w + x
        const trow = ty * tpl.w
        for (let tx = 0; tx < tpl.w; tx += step) {
          const d = frame.data[frow + tx] - tpl.data[trow + tx]
          sum += d < 0 ? -d : d
        }
        // early exit: already worse than the best candidate
        if (sum / samples > best.mad) break
      }
      const mad = sum / samples
      if (mad < best.mad) best = { x, y, mad }
    }
  }
  return best
}

/** Largest frame dimension the tracker works at; bigger frames are downscaled. */
export const TRACK_MAX_DIM = 240
/** A match with MAD at or below this is trusted; above it the target is "lost". */
export const TRACK_MAD_OK = 38
/** Search radius (in tracker pixels) while following, and while hunting for a lost target. */
export const TRACK_RADIUS = 24
export const TRACK_RADIUS_LOST = 60
/** Matches at or below this MAD are clean enough to blend into the template. */
export const TRACK_MAD_LEARN = 20
/** Share of the new patch blended into the template per confident frame. */
export const TRACK_LEARN_RATE = 0.15

export interface TrackState {
  /** Top-left of the last confident position (tracker pixels). */
  x: number
  y: number
  lost: boolean
  /** Per-step motion estimate, used to centre the next search. */
  vx?: number
  vy?: number
  /** Search the whole frame on the next step (set when tracking starts: the
   *  video was paused while the box was drawn, so the target has moved). */
  wide?: boolean
}

/**
 * One tracking step. While following, a confident match moves the box; a poor
 * match keeps the box where it was (it must never vanish) and flags it lost,
 * and the next step searches a wider area to re-acquire the target.
 * The search is centred on the position predicted from the last motion, and the
 * template slowly adapts to the target's changing appearance (mutates `tpl`).
 */
export function trackStep(frame: Gray, tpl: Gray, state: TrackState): TrackState {
  const vx = state.vx ?? 0
  const vy = state.vy ?? 0
  let m: MatchResult
  if (state.wide) {
    // whole-frame search, coarse sampling
    m = matchTemplate(frame, tpl, 0, 0, Math.max(frame.w, frame.h), 3)
  } else if (state.lost) {
    m = matchTemplate(frame, tpl, state.x, state.y, TRACK_RADIUS_LOST, 3)
  } else {
    m = matchTemplate(frame, tpl, state.x + vx, state.y + vy, TRACK_RADIUS)
  }

  if (m.mad > TRACK_MAD_OK) {
    return { x: state.x, y: state.y, lost: true, vx: 0, vy: 0, wide: state.wide }
  }

  if (m.mad <= TRACK_MAD_LEARN && !state.wide) {
    const patch = cropGray(frame, m.x, m.y, tpl.w, tpl.h)
    if (patch.w === tpl.w && patch.h === tpl.h) {
      for (let i = 0; i < tpl.data.length; i++) {
        tpl.data[i] += (patch.data[i] - tpl.data[i]) * TRACK_LEARN_RATE
      }
    }
  }

  const dx = m.x - state.x
  const dy = m.y - state.y
  return {
    x: m.x, y: m.y, lost: false,
    // smoothed velocity; ignore jumps from a wide re-acquire
    vx: state.wide || state.lost ? 0 : 0.6 * vx + 0.4 * dx,
    vy: state.wide || state.lost ? 0 : 0.6 * vy + 0.4 * dy,
  }
}
