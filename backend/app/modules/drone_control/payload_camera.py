"""
OpenCV-backed payload camera capture.

Opens either a numeric webcam index ("0", "1", ...) or an IP/RTSP/HTTP
stream URL via cv2.VideoCapture, JPEG-encodes frames, and fans them out
to WebSocket subscribers as binary frames.

The source is whatever the operator types into the UI's free-text field —
they aren't expected to know their camera app's exact stream URL format, so
a bare IP or IP:port is expanded into a short list of candidate URLs
covering the conventions used by common mobile IP-camera apps (IP Webcam,
DroidCam) and plain RTSP, tried in turn until one actually opens and yields
a frame. A full URL the operator already typed out (rtsp://, http://, ...)
is trusted as-is and tried first, unchanged.

Note: when the backend runs inside Docker, webcam index "0" opens the
*container's* video device, not the operator's host webcam, unless the
host device is passed through (e.g. --device=/dev/video0 on Linux).
On Windows/Docker Desktop there is no such passthrough — webcam capture
only works when the backend runs natively on the host.
"""
from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from dataclasses import dataclass, field

import cv2
import structlog

log = structlog.get_logger()

JPEG_QUALITY = 80
CAPTURE_FPS_CAP = 20
RECONNECT_DELAY_S = 2.0
MAX_BUFFER_DRAIN = 8   # cap on extra queued frames discarded per read (see _capture_loop)
OPEN_PROBE_TIMEOUT_S = 3.0   # per-candidate-URL time budget while probing bare IPs

# RTSP is commonly blocked/unreliable over UDP on mobile hotspots and behind
# NAT — forcing TCP transport trades a little latency for actually connecting.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

_IP_OR_IP_PORT_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?$")


def _candidate_urls(ip: str, port: str | None) -> list[str]:
    """
    Bare "IP" or "IP:port" input, expanded into the stream URL conventions
    used by popular mobile IP-camera apps, in the order most likely to
    match what the operator is actually running:
      - IP Webcam (Android): MJPEG at :8080/video
      - DroidCam:            MJPEG at :4747/video
      - Generic RTSP:        rtsp:// at the given port or the RTSP default 554
      - Plain MJPEG/HTTP:    the bare host, in case it's already a full stream
    A port explicitly given by the operator is tried first/only for the
    protocols where it makes sense, rather than overridden.
    """
    if port:
        return [
            f"http://{ip}:{port}/video",
            f"rtsp://{ip}:{port}/",
            f"http://{ip}:{port}",
        ]
    return [
        f"http://{ip}:8080/video",   # IP Webcam default
        f"http://{ip}:4747/video",   # DroidCam default
        f"rtsp://{ip}:554/",
        f"http://{ip}",
    ]


def _resolve_source(raw: str) -> int | str | list[str]:
    """
    Bare integers ("0", "1", ...) address local webcams. A bare IP or
    IP:port (no scheme) is expanded into a list of candidate stream URLs to
    probe in turn (see _candidate_urls). Anything else — the operator
    already typed a full rtsp://, http://, etc. URL — is trusted as-is and
    passed straight to OpenCV.
    """
    stripped = raw.strip()
    if stripped.isdigit():
        return int(stripped)

    m = _IP_OR_IP_PORT_RE.match(stripped)
    if m:
        ip, port = m.group(1), m.group(2)
        return _candidate_urls(ip, port)

    return stripped


TRACKER_BOX_HALF_SIZE = 40    # px — half-width/height of the initial lock box around the clicked point
TRACKER_BOX_COLOR = (0, 165, 255)   # BGR amber — matches the frontend's lock-marker colour


def _new_tracker():
    # cv2.TrackerCSRT lives under the legacy namespace in opencv-contrib
    # builds >= 4.5.1; fall back to the top-level name for older builds.
    factory = getattr(getattr(cv2, "legacy", cv2), "TrackerCSRT_create", None) \
        or getattr(cv2, "TrackerCSRT_create", None)
    if factory is None:
        raise RuntimeError("cv2.TrackerCSRT_create unavailable — install opencv-contrib-python")
    return factory()


@dataclass
class _LockState:
    """Per-subscriber object lock — each viewer tracks independently so one
    operator locking onto a target doesn't affect any other viewer of the
    same camera source."""
    tracker: object
    lost: bool = False


@dataclass
class _CaptureSession:
    source: int | str | list[str]
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    thread: threading.Thread | None = None
    stop_flag: threading.Event = field(default_factory=threading.Event)
    loop: asyncio.AbstractEventLoop | None = None
    last_error: str | None = None
    locks: dict[asyncio.Queue, _LockState] = field(default_factory=dict)
    locks_guard: threading.Lock = field(default_factory=threading.Lock)
    last_frame: object = None   # most recent decoded frame (numpy ndarray), for lock_object()


class PayloadCameraManager:
    """One capture thread per distinct source, shared across subscribers."""

    def __init__(self) -> None:
        self._sessions: dict[str, _CaptureSession] = {}
        self._lock = threading.Lock()

    def subscribe(self, raw_source: str, loop: asyncio.AbstractEventLoop) -> tuple[asyncio.Queue, str]:
        # Keyed on the operator's own input, not the resolved candidate
        # list — two subscribes of the same typed address must share one
        # capture session regardless of which candidate URL ends up working.
        key = raw_source.strip()
        source = _resolve_source(raw_source)
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)

        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                session = _CaptureSession(source=source, loop=loop)
                self._sessions[key] = session
                session.subscribers.add(queue)
                session.thread = threading.Thread(
                    target=self._capture_loop, args=(session,), daemon=True,
                )
                session.thread.start()
            else:
                session.subscribers.add(queue)

        return queue, key

    def unsubscribe(self, key: str, queue: asyncio.Queue) -> None:
        with self._lock:
            session = self._sessions.get(key)
            if not session:
                return
            session.subscribers.discard(queue)
            with session.locks_guard:
                session.locks.pop(queue, None)
            if not session.subscribers:
                session.stop_flag.set()
                del self._sessions[key]

    def lock_object(self, key: str, queue: asyncio.Queue, x: float, y: float) -> bool:
        """
        Initialize a CSRT tracker for this subscriber, centred on the given
        point (normalized 0..1 image coordinates) in the most recent frame.
        Runs on the capture thread's last decoded frame — cheap, and avoids
        races with the capture loop reading/writing the frame concurrently.
        Returns False if no frame is available yet (feed not live) or the
        tracker library is missing.
        """
        with self._lock:
            session = self._sessions.get(key)
        if not session or session.last_frame is None:
            return False

        frame = session.last_frame
        h, w = frame.shape[:2]
        cx, cy = int(x * w), int(y * h)
        x0 = max(0, cx - TRACKER_BOX_HALF_SIZE)
        y0 = max(0, cy - TRACKER_BOX_HALF_SIZE)
        bw = min(TRACKER_BOX_HALF_SIZE * 2, w - x0)
        bh = min(TRACKER_BOX_HALF_SIZE * 2, h - y0)
        if bw <= 0 or bh <= 0:
            return False

        try:
            tracker = _new_tracker()
            tracker.init(frame, (x0, y0, bw, bh))
        except Exception as e:
            log.warning("payload_camera.tracker_init_failed", error=str(e))
            return False

        with session.locks_guard:
            session.locks[queue] = _LockState(tracker=tracker)
        return True

    def unlock_object(self, key: str, queue: asyncio.Queue) -> None:
        with self._lock:
            session = self._sessions.get(key)
        if not session:
            return
        with session.locks_guard:
            session.locks.pop(queue, None)

    def _push(self, session: _CaptureSession, frame) -> None:
        if not session.loop:
            return
        for q in list(session.subscribers):
            frame_bytes = self._encode_for_subscriber(session, q, frame)
            if frame_bytes is None:
                continue

            def _put(q=q, frame_bytes=frame_bytes):
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(frame_bytes)
            session.loop.call_soon_threadsafe(_put)

    def _encode_for_subscriber(self, session: _CaptureSession, queue: asyncio.Queue, frame) -> bytes | None:
        """
        Per-subscriber: if this viewer has an active object lock, advance its
        tracker on this frame and burn the tracking box into a copy before
        encoding — a copy so one locked viewer's overlay never bleeds into
        the plain frame another viewer of the same source receives.
        """
        with session.locks_guard:
            lock_state = session.locks.get(queue)

        if lock_state is None:
            out = frame
        else:
            out = frame.copy()
            ok, box = lock_state.tracker.update(out)
            lock_state.lost = not ok
            if ok:
                x0, y0, bw, bh = (int(v) for v in box)
                cv2.rectangle(out, (x0, y0), (x0 + bw, y0 + bh), TRACKER_BOX_COLOR, 2)
                cx, cy = x0 + bw // 2, y0 + bh // 2
                cv2.drawMarker(out, (cx, cy), TRACKER_BOX_COLOR, cv2.MARKER_CROSS, 16, 2)
            else:
                cv2.putText(out, "TARGET LOST", (10, 24), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (0, 0, 255), 2, cv2.LINE_AA)

        ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        return buf.tobytes() if ok else None

    @staticmethod
    def _try_open(candidate: int | str) -> cv2.VideoCapture | None:
        """
        Opens one candidate source and confirms it actually yields a decodable
        frame within OPEN_PROBE_TIMEOUT_S — cv2.VideoCapture.isOpened() can
        return True for a URL that never delivers any data (e.g. wrong path/
        port for this particular camera app), so a real frame read is the
        only reliable signal that this candidate is the right one.
        Returns the opened, ready-to-use capture on success, else None
        (closing it first) so the caller can move on to the next candidate.
        """
        cap = cv2.VideoCapture(candidate)
        if not cap.isOpened():
            cap.release()
            return None

        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        deadline = time.monotonic() + OPEN_PROBE_TIMEOUT_S
        while time.monotonic() < deadline:
            ok, _ = cap.read()
            if ok:
                return cap
        cap.release()
        return None

    def _capture_loop(self, session: _CaptureSession) -> None:
        min_frame_interval = 1.0 / CAPTURE_FPS_CAP
        candidates = session.source if isinstance(session.source, list) else [session.source]
        # Once a candidate is confirmed working, later reconnects (a genuine
        # signal drop, not a wrong-URL guess) go straight back to it instead
        # of re-probing every candidate from scratch each time.
        known_good: int | str | None = None

        while not session.stop_flag.is_set():
            cap = None
            tried: list[str] = []
            for candidate in ([known_good] if known_good is not None else candidates):
                tried.append(str(candidate))
                cap = self._try_open(candidate)
                if cap is not None:
                    known_good = candidate
                    break

            if cap is None:
                session.last_error = (
                    f"Could not open source '{session.source}'"
                    if len(tried) == 1 else
                    f"Could not open source (tried: {', '.join(tried)})"
                )
                log.warning("payload_camera.open_failed", source=session.source, tried=tried)
                # A previously-good candidate stopped working (camera app
                # restarted on a different port, network changed, ...) —
                # forget it and re-probe every candidate next attempt.
                known_good = None
                time.sleep(RECONNECT_DELAY_S)
                continue

            log.info("payload_camera.opened", source=session.source, resolved=str(known_good))
            session.last_error = None

            while not session.stop_flag.is_set():
                t0 = time.monotonic()

                # CAP_PROP_BUFFERSIZE isn't honored by every OpenCV backend a
                # given source ends up using, so also drain a bounded number
                # of extra queued frames that arrived while we were encoding/
                # pushing the last one — grab() only fetches into the
                # driver's internal buffer without decoding, so discarding
                # backlog this way is cheap. Bounded (not "drain until
                # empty") since a fast camera can otherwise keep this loop
                # spinning indefinitely and starve the pacing sleep below.
                ok = cap.grab()
                if not ok:
                    session.last_error = "Feed read failed"
                    log.warning("payload_camera.read_failed", source=session.source)
                    break
                for _ in range(MAX_BUFFER_DRAIN):
                    if not cap.grab():
                        break
                ok, frame = cap.retrieve()
                if not ok:
                    session.last_error = "Feed read failed"
                    log.warning("payload_camera.read_failed", source=session.source)
                    break

                session.last_frame = frame
                self._push(session, frame)

                elapsed = time.monotonic() - t0
                if elapsed < min_frame_interval:
                    time.sleep(min_frame_interval - elapsed)

            cap.release()
            if not session.stop_flag.is_set():
                time.sleep(RECONNECT_DELAY_S)   # source dropped — retry

        log.info("payload_camera.stopped", source=session.source)


payload_camera_manager = PayloadCameraManager()
