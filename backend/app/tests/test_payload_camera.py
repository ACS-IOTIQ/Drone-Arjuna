"""
Payload camera module tests
===========================
app.modules.drone_control.payload_camera  +  WS /api/drone-control/camera-stream

(Lock-box persistence when the tracker is unavailable / raising is covered in
test_payload_camera_persistence.py; this file covers everything around it.)

Covers:
  - validate_camera_source: SSRF guard (schemes, loopback / private / link-local /
    metadata / multicast / unspecified hosts, DNS failures, mixed DNS answers,
    CAMERA_ALLOWED_HOSTS bypass, malformed input)
  - _resolve_source / _candidate_urls: webcam index, bare IP[:port] expansion order,
    full URLs passed through untouched
  - _clean_label: printable-ASCII only, trimmed, length-capped
  - PayloadCameraManager lifecycle: one capture session per typed source shared by
    all viewers, last viewer out stops the capture thread
  - lock_object geometry and failure cases; per-subscriber independence of locks
  - tracker success / lost / recovered overlay states; imencode failure
  - _push fan-out: drops the oldest frame when a viewer's queue is full
  - _try_open: opened-but-silent sources are rejected
  - _capture_loop: candidate probing order, error reporting, reconnect goes straight
    back to the last working candidate
  - WebSocket route: auth (4401 / 4403), bad source (4400), frame delivery,
    lock / name / unlock commands, malformed input ignored, cleanup on disconnect
"""
import asyncio
import json
import socket
import threading
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import quote

import cv2
import numpy as np
import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import get_settings
from app.modules.drone_control import payload_camera as pc
from app.modules.drone_control.payload_camera import (
    PayloadCameraManager,
    _CaptureSession,
    _candidate_urls,
    _clean_label,
    _resolve_source,
    validate_camera_source,
)


def _frame(w=320, h=240):
    return np.full((h, w, 3), 40, dtype=np.uint8)


def _decode(jpeg: bytes) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)


def _amber_pixels(img: np.ndarray) -> int:
    target = np.array(pc.TRACKER_BOX_COLOR, dtype=np.int16)
    return int((np.abs(img.astype(np.int16) - target).sum(axis=2) < 90).sum())


def _red_pixels(img: np.ndarray) -> int:
    return int(((img[:, :, 2] > 200) & (img[:, :, 1] < 60) & (img[:, :, 0] < 60)).sum())


# ══════════════════════════════════════════════════════════════════════
# validate_camera_source  (SSRF guard)
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def dns(monkeypatch):
    """Deterministic DNS: names map to the IPs given; IP literals resolve to themselves."""
    table: dict[str, list[str]] = {}

    def _getaddrinfo(host, port, *a, **k):
        if host in table:
            ips = table[host]
        elif host.replace(".", "").replace(":", "").isalnum() and (
            host.count(".") == 3 or ":" in host
        ):
            ips = [host]                      # IP literal
        else:
            raise socket.gaierror("no such host")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]

    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
    return table


@pytest.mark.parametrize("raw", ["0", "1", "12", " 3 ", "007"])
def test_validate_accepts_webcam_index(raw):
    validate_camera_source(raw)            # does not raise, never touches DNS


@pytest.mark.parametrize("raw", [
    "8.8.8.8",
    "8.8.8.8:8080",
    "http://8.8.8.8:8080/video",
    "https://93.184.216.34/stream",
    "rtsp://93.184.216.34:554/live",
    "RTSP://93.184.216.34/live",           # scheme is case-insensitive
])
def test_validate_accepts_public_hosts(raw, dns):
    validate_camera_source(raw)


def test_validate_accepts_public_hostname(dns):
    dns["cam.example.com"] = ["93.184.216.34"]
    validate_camera_source("https://cam.example.com/stream.mjpg")


@pytest.mark.parametrize("raw", [
    "",
    "   ",
    "9" * 513,                             # over the 512 length cap
    "http://8.8.8.8/\r\nHost: evil",       # header injection
    "http://8.8.8.8/\x00",
    "not a url",
    "cam.local",                           # bare hostname, no scheme -> unsupported
    "999.1",
    "1.2.3",
    "8.8.8.8:abc",
])
def test_validate_rejects_malformed_input(raw, dns):
    with pytest.raises(ValueError):
        validate_camera_source(raw)


@pytest.mark.parametrize("raw", [
    "file:///etc/passwd",
    "ftp://8.8.8.8/x",
    "gopher://8.8.8.8/",
    "javascript:alert(1)",
    "data:text/plain,hi",
    "ws://8.8.8.8/",
    "http://",                             # scheme but no host
])
def test_validate_rejects_unsupported_schemes(raw, dns):
    with pytest.raises(ValueError):
        validate_camera_source(raw)


@pytest.mark.parametrize("raw", [
    "127.0.0.1",
    "127.0.0.1:8000",
    "http://127.0.0.1:8000/admin",
    "http://[::1]/",
    "10.0.0.5",
    "172.16.0.9:8080",
    "192.168.1.20",
    "http://192.168.1.20:8080/video",
    "169.254.169.254",                     # cloud metadata endpoint
    "http://169.254.169.254/latest/meta-data/",
    "0.0.0.0",
    "224.0.0.1",                           # multicast
    "240.0.0.1",                           # reserved
])
def test_validate_rejects_internal_addresses(raw, dns):
    with pytest.raises(ValueError, match="not permitted"):
        validate_camera_source(raw)


def test_validate_rejects_hostname_resolving_to_private(dns):
    dns["internal.corp"] = ["10.1.2.3"]
    with pytest.raises(ValueError, match="not permitted"):
        validate_camera_source("http://internal.corp/stream")


def test_validate_rejects_dns_rebinding_style_mixed_answers(dns):
    """One public and one private A record: the private one must still block it."""
    dns["mixed.example.com"] = ["93.184.216.34", "127.0.0.1"]
    with pytest.raises(ValueError, match="not permitted"):
        validate_camera_source("http://mixed.example.com/")


def test_validate_rejects_unresolvable_host(dns):
    with pytest.raises(ValueError, match="does not resolve"):
        validate_camera_source("http://no-such-host.invalid/stream")


def test_validate_allowed_hosts_bypass_private_check(monkeypatch, dns):
    monkeypatch.setattr(get_settings(), "camera_allowed_hosts_str", "192.168.1.20, Cam.Lab")
    validate_camera_source("192.168.1.20:8080")
    validate_camera_source("http://192.168.1.20/video")
    validate_camera_source("http://CAM.LAB/stream")       # compared case-insensitively
    with pytest.raises(ValueError):                         # a different private host stays blocked
        validate_camera_source("192.168.1.21")


def test_validate_allowed_hosts_does_not_allow_bad_schemes(monkeypatch, dns):
    monkeypatch.setattr(get_settings(), "camera_allowed_hosts_str", "192.168.1.20")
    with pytest.raises(ValueError):
        validate_camera_source("file://192.168.1.20/etc/passwd")


# ══════════════════════════════════════════════════════════════════════
# _resolve_source / _candidate_urls / _clean_label
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,expected", [("0", 0), ("2", 2), ("  4 ", 4)])
def test_resolve_source_webcam_index(raw, expected):
    assert _resolve_source(raw) == expected


def test_resolve_bare_ip_expands_to_app_conventions_in_order():
    assert _resolve_source("192.168.1.5") == [
        "http://192.168.1.5:8080/video",     # IP Webcam
        "http://192.168.1.5:4747/video",     # DroidCam
        "rtsp://192.168.1.5:554/",           # generic RTSP
        "http://192.168.1.5",                # plain host
    ]


def test_resolve_ip_with_port_tries_only_that_port():
    assert _resolve_source("192.168.1.5:9000") == [
        "http://192.168.1.5:9000/video",
        "rtsp://192.168.1.5:9000/",
        "http://192.168.1.5:9000",
    ]


@pytest.mark.parametrize("raw", [
    "rtsp://user:pw@10.0.0.9:554/stream1",
    "http://cam.example.com/mjpeg",
    "https://cam.example.com/hls.m3u8",
])
def test_resolve_full_url_is_trusted_as_is(raw):
    assert _resolve_source(raw) == raw


def test_resolve_full_url_is_stripped_only():
    assert _resolve_source("  rtsp://h/x  ") == "rtsp://h/x"


def test_candidate_urls_directly():
    assert _candidate_urls("1.2.3.4", None)[0] == "http://1.2.3.4:8080/video"
    assert _candidate_urls("1.2.3.4", "81")[0] == "http://1.2.3.4:81/video"
    assert len(_candidate_urls("1.2.3.4", None)) == 4
    assert len(_candidate_urls("1.2.3.4", "81")) == 3


def test_clean_label_keeps_printable_ascii():
    assert _clean_label("TARGET-1 (alpha)") == "TARGET-1 (alpha)"


@pytest.mark.parametrize("raw,expected", [
    ("  padded  ", "padded"),
    ("tab\there", "tabhere"),
    ("new\nline", "newline"),
    ("café", "caf"),                       # non-ASCII dropped, cv2.putText can't render it
    ("車両-7", "-7"),
    ("\x00\x1fX\x7f", "X"),
    ("", ""),
])
def test_clean_label_strips_unrenderable_characters(raw, expected):
    assert _clean_label(raw) == expected


@pytest.mark.parametrize("value", [None, 5, 1.5, ["a"], {"a": 1}, b"bytes"])
def test_clean_label_non_string_is_empty(value):
    assert _clean_label(value) == ""


def test_clean_label_is_length_capped():
    out = _clean_label("A" * 500)
    assert out == "A" * pc.MAX_LABEL_LEN


# ══════════════════════════════════════════════════════════════════════
# PayloadCameraManager — subscribe / unsubscribe lifecycle
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def manager(monkeypatch):
    """A fresh manager whose capture thread is a no-op (no real camera is opened)."""
    started: list[_CaptureSession] = []
    monkeypatch.setattr(PayloadCameraManager, "_capture_loop", lambda self, s: started.append(s))
    m = PayloadCameraManager()
    m._started = started
    return m


async def test_subscribe_starts_one_capture_session(manager):
    loop = asyncio.get_running_loop()
    queue, key = manager.subscribe("  192.168.1.5  ", loop)
    assert key == "192.168.1.5"                        # keyed on the operator's trimmed input
    assert queue.maxsize == 2
    session = manager._sessions[key]
    assert session.subscribers == {queue}
    assert session.loop is loop
    assert session.source == _resolve_source("192.168.1.5")
    session.thread.join(timeout=2)
    assert manager._started == [session]


async def test_second_viewer_shares_the_capture_session(manager):
    loop = asyncio.get_running_loop()
    q1, key1 = manager.subscribe("0", loop)
    q2, key2 = manager.subscribe(" 0 ", loop)          # same camera typed with stray spaces
    assert key1 == key2 == "0"
    assert q1 is not q2
    assert len(manager._sessions) == 1
    assert manager._sessions["0"].subscribers == {q1, q2}
    manager._sessions["0"].thread.join(timeout=2)
    assert len(manager._started) == 1                  # only one capture thread was started


async def test_different_sources_get_separate_sessions(manager):
    loop = asyncio.get_running_loop()
    manager.subscribe("0", loop)
    manager.subscribe("1", loop)
    manager.subscribe("rtsp://8.8.8.8/x", loop)
    assert set(manager._sessions) == {"0", "1", "rtsp://8.8.8.8/x"}


async def test_unsubscribe_keeps_session_while_viewers_remain(manager):
    loop = asyncio.get_running_loop()
    q1, key = manager.subscribe("0", loop)
    q2, _ = manager.subscribe("0", loop)
    manager.unsubscribe(key, q1)
    session = manager._sessions[key]
    assert session.subscribers == {q2}
    assert not session.stop_flag.is_set()


async def test_last_unsubscribe_stops_capture_and_removes_session(manager):
    loop = asyncio.get_running_loop()
    q, key = manager.subscribe("0", loop)
    session = manager._sessions[key]
    manager.unsubscribe(key, q)
    assert session.stop_flag.is_set()
    assert key not in manager._sessions


async def test_unsubscribe_unknown_key_is_a_noop(manager):
    manager.unsubscribe("nope", asyncio.Queue())       # must not raise


async def test_unsubscribe_drops_that_viewers_lock(manager):
    loop = asyncio.get_running_loop()
    q1, key = manager.subscribe("0", loop)
    q2, _ = manager.subscribe("0", loop)
    session = manager._sessions[key]
    session.last_frame = _frame()
    manager.lock_object(key, q1, 0.5, 0.5)
    manager.lock_object(key, q2, 0.5, 0.5)
    manager.unsubscribe(key, q1)
    assert q1 not in session.locks and q2 in session.locks


async def test_resubscribe_after_full_teardown_starts_a_new_session(manager):
    loop = asyncio.get_running_loop()
    q, key = manager.subscribe("0", loop)
    first = manager._sessions[key]
    manager.unsubscribe(key, q)
    manager.subscribe("0", loop)
    assert manager._sessions[key] is not first
    assert not manager._sessions[key].stop_flag.is_set()


# ══════════════════════════════════════════════════════════════════════
# lock_object / name_object / unlock_object
# ══════════════════════════════════════════════════════════════════════

class _RecordingTracker:
    def __init__(self):
        self.init_args = None

    def init(self, frame, box):
        self.init_args = (frame.shape, tuple(box))
        return True

    def update(self, frame):
        return True, (10, 20, 30, 40)


@pytest.fixture
def cam(monkeypatch):
    """Manager with one live session ("cam") holding a 320x240 frame."""
    m = PayloadCameraManager()
    s = _CaptureSession(source=0, loop=None)
    s.last_frame = _frame(320, 240)
    m._sessions["cam"] = s
    tracker = _RecordingTracker()
    monkeypatch.setattr(pc, "_new_tracker", lambda: tracker)
    m._tracker = tracker
    return m, s


async def test_lock_unknown_source_returns_false(cam):
    manager, _ = cam
    assert manager.lock_object("missing", asyncio.Queue(), 0.5, 0.5) is False


async def test_lock_before_first_frame_returns_false(cam):
    manager, session = cam
    session.last_frame = None
    q = asyncio.Queue()
    assert manager.lock_object("cam", q, 0.5, 0.5) is False
    assert q not in session.locks


async def test_lock_default_box_is_centred_with_fixed_half_size(cam):
    manager, session = cam
    q = asyncio.Queue()
    assert manager.lock_object("cam", q, 0.5, 0.5) is True
    half = pc.TRACKER_BOX_HALF_SIZE
    assert session.locks[q].last_box == (160 - half, 120 - half, half * 2, half * 2)
    assert manager._tracker.init_args == ((240, 320, 3), (160 - half, 120 - half, half * 2, half * 2))


async def test_lock_box_size_from_fractions_of_the_frame(cam):
    manager, session = cam
    q = asyncio.Queue()
    manager.lock_object("cam", q, 0.5, 0.5, hw=0.1, hh=0.25)
    # 0.1*320 = 32 px half-width, 0.25*240 = 60 px half-height
    assert session.locks[q].last_box == (160 - 32, 120 - 60, 64, 120)


async def test_lock_box_is_clamped_to_the_top_left_corner(cam):
    manager, session = cam
    q = asyncio.Queue()
    assert manager.lock_object("cam", q, 0.0, 0.0) is True
    x0, y0, bw, bh = session.locks[q].last_box
    assert (x0, y0) == (0, 0)
    assert bw <= 320 and bh <= 240 and bw > 0 and bh > 0


async def test_lock_box_is_clamped_to_the_bottom_right_corner(cam):
    manager, session = cam
    q = asyncio.Queue()
    assert manager.lock_object("cam", q, 1.0, 1.0) is True
    x0, y0, bw, bh = session.locks[q].last_box
    assert x0 + bw <= 320 and y0 + bh <= 240


async def test_lock_point_far_outside_the_frame_is_rejected(cam):
    manager, session = cam
    q = asyncio.Queue()
    assert manager.lock_object("cam", q, 5.0, 5.0) is False
    assert q not in session.locks


async def test_lock_stores_cleaned_name(cam):
    manager, session = cam
    q = asyncio.Queue()
    manager.lock_object("cam", q, 0.5, 0.5, name="  Tänk-1 ")
    assert session.locks[q].name == "Tnk-1"


async def test_locking_again_replaces_the_previous_lock(cam):
    manager, session = cam
    q = asyncio.Queue()
    manager.lock_object("cam", q, 0.25, 0.25, name="A")
    first = session.locks[q]
    manager.lock_object("cam", q, 0.75, 0.75, name="B")
    assert session.locks[q] is not first
    assert session.locks[q].name == "B"


async def test_name_object_updates_only_an_existing_lock(cam):
    manager, session = cam
    locked, unlocked = asyncio.Queue(), asyncio.Queue()
    manager.lock_object("cam", locked, 0.5, 0.5, name="old")
    manager.name_object("cam", locked, "new\x00name")
    manager.name_object("cam", unlocked, "ignored")           # no lock -> nothing created
    assert session.locks[locked].name == "newname"
    assert unlocked not in session.locks
    manager.name_object("missing", locked, "x")               # unknown source: no error


async def test_unlock_object_removes_only_that_viewers_lock(cam):
    manager, session = cam
    a, b = asyncio.Queue(), asyncio.Queue()
    manager.lock_object("cam", a, 0.5, 0.5)
    manager.lock_object("cam", b, 0.5, 0.5)
    manager.unlock_object("cam", a)
    assert a not in session.locks and b in session.locks
    manager.unlock_object("cam", a)                            # idempotent
    manager.unlock_object("missing", a)                        # unknown source: no error


async def test_locks_are_independent_per_viewer(cam):
    manager, session = cam
    locked, plain = asyncio.Queue(), asyncio.Queue()
    manager.lock_object("cam", locked, 0.5, 0.5, hw=0.1, hh=0.1)
    frame = session.last_frame
    with_overlay = manager._encode_for_subscriber(session, locked, frame)
    without = manager._encode_for_subscriber(session, plain, frame)
    assert with_overlay != without
    assert _amber_pixels(_decode(without)) == 0                 # the plain viewer sees no box
    assert _amber_pixels(_decode(with_overlay)) > 50
    assert int(frame.sum()) == int(_frame().sum())             # shared source frame never painted on


# ══════════════════════════════════════════════════════════════════════
# _encode_for_subscriber — tracker states
# ══════════════════════════════════════════════════════════════════════

class _SequenceTracker:
    """update() returns the given (ok, box) results one per frame, repeating the last."""

    def __init__(self, results):
        self.results = list(results)

    def init(self, *a, **k):
        return True

    def update(self, frame):
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


async def test_successful_tracking_follows_the_new_box(cam, monkeypatch):
    manager, session = cam
    monkeypatch.setattr(pc, "_new_tracker", lambda: _SequenceTracker([(True, (50.0, 60.0, 70.0, 80.0))]))
    q = asyncio.Queue()
    manager.lock_object("cam", q, 0.5, 0.5)
    img = _decode(manager._encode_for_subscriber(session, q, session.last_frame))
    assert session.locks[q].last_box == (50, 60, 70, 80)         # ints, from the tracker
    assert session.locks[q].lost is False
    assert _amber_pixels(img) > 100 and _red_pixels(img) == 0


async def test_target_lost_then_recovered(cam, monkeypatch):
    manager, session = cam
    monkeypatch.setattr(pc, "_new_tracker", lambda: _SequenceTracker([
        (False, (0, 0, 0, 0)),                 # frame 1: lost
        (True, (100, 100, 40, 40)),            # frame 2: re-acquired
    ]))
    q = asyncio.Queue()
    manager.lock_object("cam", q, 0.5, 0.5)

    lost_img = _decode(manager._encode_for_subscriber(session, q, session.last_frame))
    assert session.locks[q].lost is True
    assert _red_pixels(lost_img) > 100

    ok_img = _decode(manager._encode_for_subscriber(session, q, session.last_frame))
    assert session.locks[q].lost is False
    assert session.locks[q].last_box == (100, 100, 40, 40)
    assert _red_pixels(ok_img) == 0 and _amber_pixels(ok_img) > 100


async def test_frame_without_a_lock_is_encoded_unchanged(cam):
    manager, session = cam
    jpeg = manager._encode_for_subscriber(session, asyncio.Queue(), session.last_frame)
    img = _decode(jpeg)
    assert img.shape == (240, 320, 3)
    assert abs(float(img.mean()) - 40.0) < 3


async def test_encode_returns_none_when_jpeg_encoding_fails(cam, monkeypatch):
    manager, session = cam
    monkeypatch.setattr(cv2, "imencode", lambda *a, **k: (False, None))
    assert manager._encode_for_subscriber(session, asyncio.Queue(), session.last_frame) is None


# ══════════════════════════════════════════════════════════════════════
# _push — fan-out to viewers
# ══════════════════════════════════════════════════════════════════════

async def _drain_loop():
    for _ in range(3):
        await asyncio.sleep(0)


async def test_push_delivers_a_jpeg_to_every_viewer():
    m = PayloadCameraManager()
    session = _CaptureSession(source=0, loop=asyncio.get_running_loop())
    q1, q2 = asyncio.Queue(maxsize=2), asyncio.Queue(maxsize=2)
    session.subscribers = {q1, q2}
    m._push(session, _frame())
    await _drain_loop()
    for q in (q1, q2):
        data = q.get_nowait()
        assert isinstance(data, bytes) and data[:2] == b"\xff\xd8"      # JPEG magic


async def test_push_without_a_loop_is_a_noop():
    m = PayloadCameraManager()
    session = _CaptureSession(source=0, loop=None)
    q = asyncio.Queue(maxsize=2)
    session.subscribers = {q}
    m._push(session, _frame())
    await _drain_loop()
    assert q.empty()


async def test_push_drops_the_oldest_frame_when_a_viewer_is_slow():
    m = PayloadCameraManager()
    session = _CaptureSession(source=0, loop=asyncio.get_running_loop())
    q = asyncio.Queue(maxsize=2)
    session.subscribers = {q}
    frames = [np.full((24, 32, 3), v, dtype=np.uint8) for v in (10, 120, 240)]
    for f in frames:
        m._push(session, f)
    await _drain_loop()
    assert q.qsize() == 2                                    # bounded: never grows past maxsize
    means = [float(_decode(q.get_nowait()).mean()) for _ in range(2)]
    assert means[0] > 100 and means[1] > 200                 # the two NEWEST frames survived


async def test_push_skips_a_viewer_whose_frame_cannot_be_encoded(monkeypatch):
    m = PayloadCameraManager()
    session = _CaptureSession(source=0, loop=asyncio.get_running_loop())
    q = asyncio.Queue(maxsize=2)
    session.subscribers = {q}
    monkeypatch.setattr(cv2, "imencode", lambda *a, **k: (False, None))
    m._push(session, _frame())
    await _drain_loop()
    assert q.empty()


# ══════════════════════════════════════════════════════════════════════
# _try_open
# ══════════════════════════════════════════════════════════════════════

class _FakeCap:
    """Scriptable cv2.VideoCapture replacement."""

    def __init__(self, opened=True, reads=None, grabs=None):
        self.opened = opened
        self.reads = reads                      # None -> always ok; list -> scripted results
        self.grabs = grabs
        self.released = False
        self.props = {}
        self.frame = _frame(64, 48)

    def isOpened(self):
        return self.opened

    def release(self):
        self.released = True

    def set(self, prop, value):
        self.props[prop] = value

    def read(self):
        if self.reads is None:
            return True, self.frame
        return (self.reads.pop(0), self.frame) if self.reads else (False, None)

    def grab(self):
        if self.grabs is None:
            return True
        return self.grabs.pop(0) if self.grabs else False

    def retrieve(self):
        return True, self.frame


def test_try_open_returns_none_and_releases_when_not_opened(monkeypatch):
    cap = _FakeCap(opened=False)
    monkeypatch.setattr(cv2, "VideoCapture", lambda c: cap)
    assert PayloadCameraManager._try_open("http://8.8.8.8/x") is None
    assert cap.released is True


def test_try_open_returns_capture_once_a_frame_decodes(monkeypatch):
    cap = _FakeCap(opened=True)
    monkeypatch.setattr(cv2, "VideoCapture", lambda c: cap)
    assert PayloadCameraManager._try_open(0) is cap
    assert cap.props[cv2.CAP_PROP_BUFFERSIZE] == 1            # latency: keep the buffer tiny
    assert cap.released is False


def test_try_open_rejects_a_source_that_opens_but_never_sends_frames(monkeypatch):
    cap = _FakeCap(opened=True, reads=[False] * 10_000)
    monkeypatch.setattr(cv2, "VideoCapture", lambda c: cap)
    monkeypatch.setattr(pc, "OPEN_PROBE_TIMEOUT_S", 0.05)
    t0 = time.monotonic()
    assert PayloadCameraManager._try_open("http://8.8.8.8/wrong") is None
    assert time.monotonic() - t0 < 2                          # gave up at the probe budget
    assert cap.released is True


def test_try_open_accepts_a_late_first_frame(monkeypatch):
    cap = _FakeCap(opened=True, reads=[False, False, True])
    monkeypatch.setattr(cv2, "VideoCapture", lambda c: cap)
    assert PayloadCameraManager._try_open(0) is cap


# ══════════════════════════════════════════════════════════════════════
# _capture_loop
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def fast_loop(monkeypatch):
    monkeypatch.setattr(pc, "RECONNECT_DELAY_S", 0.01)
    monkeypatch.setattr(pc, "CAPTURE_FPS_CAP", 1000)


def _run_loop(manager, session, timeout=3.0):
    t = threading.Thread(target=manager._capture_loop, args=(session,), daemon=True)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), "capture loop did not stop"


def test_capture_loop_pushes_frames_and_records_last_frame(monkeypatch, fast_loop):
    manager = PayloadCameraManager()
    session = _CaptureSession(source=0, loop=None)
    pushed = []
    cap = _FakeCap(opened=True)
    monkeypatch.setattr(cv2, "VideoCapture", lambda c: cap)

    def _push(s, frame):
        pushed.append(frame)
        if len(pushed) == 3:
            s.stop_flag.set()

    monkeypatch.setattr(manager, "_push", _push)
    _run_loop(manager, session)

    assert len(pushed) == 3
    assert session.last_frame is cap.frame
    assert session.last_error is None
    assert cap.released is True                                # capture is released on stop


def test_capture_loop_tries_candidates_in_order_until_one_works(monkeypatch, fast_loop):
    manager = PayloadCameraManager()
    candidates = ["http://h:8080/video", "http://h:4747/video", "rtsp://h:554/"]
    session = _CaptureSession(source=candidates, loop=None)
    tried = []

    def _try_open(candidate):
        tried.append(candidate)
        if candidate == candidates[1]:
            session.stop_flag.set()                           # stop after the first success
            return _FakeCap(opened=True)
        return None

    monkeypatch.setattr(PayloadCameraManager, "_try_open", staticmethod(_try_open))
    monkeypatch.setattr(manager, "_push", lambda s, f: None)
    _run_loop(manager, session)
    assert tried == candidates[:2]                            # the third was never needed


def test_capture_loop_reports_every_candidate_tried_when_none_open(monkeypatch, fast_loop):
    manager = PayloadCameraManager()
    candidates = ["http://h:8080/video", "rtsp://h:554/"]
    session = _CaptureSession(source=candidates, loop=None)
    calls = []

    def _try_open(candidate):
        calls.append(candidate)
        if len(calls) == len(candidates):
            session.stop_flag.set()
        return None

    monkeypatch.setattr(PayloadCameraManager, "_try_open", staticmethod(_try_open))
    _run_loop(manager, session)
    assert session.last_error == "Could not open source (tried: http://h:8080/video, rtsp://h:554/)"


def test_capture_loop_single_source_error_message(monkeypatch, fast_loop):
    manager = PayloadCameraManager()
    session = _CaptureSession(source=3, loop=None)

    def _try_open(candidate):
        session.stop_flag.set()
        return None

    monkeypatch.setattr(PayloadCameraManager, "_try_open", staticmethod(_try_open))
    _run_loop(manager, session)
    assert session.last_error == "Could not open source '3'"


def test_capture_loop_reconnects_straight_to_the_last_working_candidate(monkeypatch, fast_loop):
    manager = PayloadCameraManager()
    session = _CaptureSession(source=["bad", "good"], loop=None)
    calls = []

    def _try_open(candidate):
        calls.append(candidate)
        if candidate == "bad":
            return None
        if len(calls) == 2:
            return _FakeCap(opened=True, grabs=[])            # first grab fails -> connection dropped
        session.stop_flag.set()
        return _FakeCap(opened=True)

    monkeypatch.setattr(PayloadCameraManager, "_try_open", staticmethod(_try_open))
    monkeypatch.setattr(manager, "_push", lambda s, f: None)
    _run_loop(manager, session)
    # probe bad, probe good, drop -> reconnect goes to "good" only (no re-probe of "bad")
    assert calls == ["bad", "good", "good"]


def test_capture_loop_flags_a_failed_read_and_retries(monkeypatch, fast_loop):
    manager = PayloadCameraManager()
    session = _CaptureSession(source=0, loop=None)
    errors_seen = []
    opened = []

    def _try_open(candidate):
        opened.append(candidate)
        errors_seen.append(session.last_error)                # what the first attempt left behind
        if len(opened) == 2:
            session.stop_flag.set()
        return _FakeCap(opened=True, grabs=[])                # grab() fails immediately

    monkeypatch.setattr(PayloadCameraManager, "_try_open", staticmethod(_try_open))
    _run_loop(manager, session)
    assert len(opened) == 2                                    # it came back for another attempt
    assert errors_seen == [None, "Feed read failed"]           # the failed read was reported, then retried
    assert session.last_error is None                          # cleared again once reopened


def test_capture_loop_forgets_a_known_good_candidate_that_stops_opening(monkeypatch, fast_loop):
    manager = PayloadCameraManager()
    session = _CaptureSession(source=["a", "b"], loop=None)
    calls = []

    def _try_open(candidate):
        calls.append(candidate)
        n = len(calls)
        if n == 1:
            return _FakeCap(opened=True, grabs=[])            # "a" works, then drops
        if n == 3:
            session.stop_flag.set()                           # stop once the re-probe has begun
        return None                                           # "a" no longer opens

    monkeypatch.setattr(PayloadCameraManager, "_try_open", staticmethod(_try_open))
    monkeypatch.setattr(manager, "_push", lambda s, f: None)
    _run_loop(manager, session)
    # 1: probe "a" (works) -> drops; 2: reconnect to known-good "a" only (fails) -> forgotten;
    # 3-4: full re-probe of every candidate, "a" then "b"
    assert calls == ["a", "a", "a", "b"]


def test_capture_loop_exits_immediately_when_already_stopped(monkeypatch):
    manager = PayloadCameraManager()
    session = _CaptureSession(source=0, loop=None)
    session.stop_flag.set()
    monkeypatch.setattr(PayloadCameraManager, "_try_open", staticmethod(lambda c: pytest.fail("opened")))
    _run_loop(manager, session)


def test_capture_loop_drains_backlog_before_decoding(monkeypatch, fast_loop):
    """grab() is called more than once per delivered frame to discard queued backlog."""
    manager = PayloadCameraManager()
    session = _CaptureSession(source=0, loop=None)
    cap = _FakeCap(opened=True)
    grab_calls = []
    orig_grab = cap.grab
    cap.grab = lambda: (grab_calls.append(1), orig_grab())[1]
    monkeypatch.setattr(cv2, "VideoCapture", lambda c: cap)

    def _push(s, frame):
        s.stop_flag.set()

    monkeypatch.setattr(manager, "_push", _push)
    _run_loop(manager, session)
    assert len(grab_calls) == 1 + pc.MAX_BUFFER_DRAIN


# ══════════════════════════════════════════════════════════════════════
# WS /api/drone-control/camera-stream
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def ws_client(monkeypatch):
    """Starlette TestClient on the real app with no startup side effects."""
    import app.modules.drone_control.router as router_mod
    from app.main import app

    @asynccontextmanager
    async def _noop_lifespan(a):
        yield

    @asynccontextmanager
    async def _no_db():
        yield MagicMock()

    original = app.router.lifespan_context
    app.router.lifespan_context = _noop_lifespan
    monkeypatch.setattr(router_mod, "AsyncSessionLocal", _no_db)
    try:
        with TestClient(app, raise_server_exceptions=False) as tc:
            yield tc, router_mod
    finally:
        app.router.lifespan_context = original


@pytest.fixture
def fake_manager(ws_client, monkeypatch):
    """Authenticated user + a stand-in camera manager that hands out one queue."""
    _, router_mod = ws_client
    monkeypatch.setattr(router_mod, "authenticate_ws", AsyncMock(return_value=MagicMock()))
    mgr = MagicMock()
    holder = {}

    def _subscribe(source, loop):
        q = asyncio.Queue(maxsize=2)
        q.put_nowait(b"\xff\xd8FRAME-1")
        holder["queue"] = q
        return q, source.strip()

    mgr.subscribe.side_effect = _subscribe
    mgr.holder = holder
    monkeypatch.setattr(router_mod, "payload_camera_manager", mgr)
    return mgr


URL = "/api/drone-control/camera-stream"


def _receive(ws, method="receive_text", timeout=5.0):
    """ws.receive_*() with a deadline.

    Starlette's TestClient blocks forever on a receive when the server has nothing to send
    (e.g. the route returned without a close frame). Fail the test instead of hanging the run.
    """
    box = {}

    def _run():
        try:
            box["value"] = getattr(ws, method)()
        except BaseException as exc:          # re-raised below, e.g. WebSocketDisconnect
            box["error"] = exc

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        pytest.fail(f"no websocket message within {timeout}s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def test_ws_without_ticket_is_rejected_4401(ws_client):
    tc, _ = ws_client
    with pytest.raises(WebSocketDisconnect) as exc:
        with tc.websocket_connect(f"{URL}?source=0"):
            pass
    assert exc.value.code == 4401


def test_ws_with_jwt_in_query_instead_of_ticket_is_rejected(ws_client):
    tc, _ = ws_client
    with pytest.raises(WebSocketDisconnect) as exc:
        with tc.websocket_connect(f"{URL}?source=0&token=eyJhbGciOi.fake.jwt"):
            pass
    assert exc.value.code == 4401


def test_ws_invalid_or_used_ticket_is_rejected_4401(ws_client, monkeypatch):
    tc, router_mod = ws_client
    monkeypatch.setattr(router_mod, "authenticate_ws",
                        AsyncMock(side_effect=HTTPException(status_code=401, detail="Unauthorized")))
    with pytest.raises(WebSocketDisconnect) as exc:
        with tc.websocket_connect(f"{URL}?source=0&ticket=used-or-bad"):
            pass
    assert exc.value.code == 4401


def test_ws_insufficient_role_is_rejected_4403(ws_client, monkeypatch):
    tc, router_mod = ws_client
    auth = AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden"))
    monkeypatch.setattr(router_mod, "authenticate_ws", auth)
    with pytest.raises(WebSocketDisconnect) as exc:
        with tc.websocket_connect(f"{URL}?source=0&ticket=viewer-ticket"):
            pass
    assert exc.value.code == 4403
    assert auth.await_args.kwargs["min_role"] == "flight_controller"     # viewers may not watch


def test_ws_missing_source_param_is_refused(ws_client):
    tc, _ = ws_client
    with pytest.raises(Exception):
        with tc.websocket_connect(f"{URL}?ticket=t"):
            pass


@pytest.mark.parametrize("source", [
    "file:///etc/passwd",
    "ftp://8.8.8.8/x",
    "127.0.0.1",
    "http://169.254.169.254/latest/meta-data/",
    "192.168.1.20:8080",
    "not a url",
])
def test_ws_unsafe_source_is_rejected_4400_and_never_subscribed(ws_client, fake_manager, source):
    tc, _ = ws_client
    with pytest.raises(WebSocketDisconnect) as exc:
        with tc.websocket_connect(f"{URL}?source={quote(source, safe='')}&ticket=t"):
            pass
    assert exc.value.code == 4400
    fake_manager.subscribe.assert_not_called()


def test_ws_streams_binary_frames_to_the_client(ws_client, fake_manager):
    tc, _ = ws_client
    with tc.websocket_connect(f"{URL}?source=0&ticket=t") as ws:
        assert _receive(ws, "receive_bytes") == b"\xff\xd8FRAME-1"
    fake_manager.subscribe.assert_called_once()
    assert fake_manager.subscribe.call_args.args[0] == "0"


def test_ws_unsubscribes_when_the_client_disconnects(ws_client, fake_manager):
    tc, _ = ws_client
    with tc.websocket_connect(f"{URL}?source=0&ticket=t") as ws:
        _receive(ws, "receive_bytes")
    fake_manager.unsubscribe.assert_called_once_with("0", fake_manager.holder["queue"])


def test_ws_lock_command_passes_normalised_coordinates(ws_client, fake_manager):
    tc, _ = ws_client
    with tc.websocket_connect(f"{URL}?source=0&ticket=t") as ws:
        _receive(ws, "receive_bytes")
        ws.send_text(json.dumps({"cmd": "lock", "x": 0.5, "y": 0.25, "hw": 0.1, "hh": 0.2, "name": "T1"}))
    q = fake_manager.holder["queue"]
    fake_manager.lock_object.assert_called_once_with("0", q, 0.5, 0.25, 0.1, 0.2, "T1")


def test_ws_lock_accepts_integer_coordinates(ws_client, fake_manager):
    tc, _ = ws_client
    with tc.websocket_connect(f"{URL}?source=0&ticket=t") as ws:
        _receive(ws, "receive_bytes")
        ws.send_text(json.dumps({"cmd": "lock", "x": 1, "y": 0}))
    q = fake_manager.holder["queue"]
    fake_manager.lock_object.assert_called_once_with("0", q, 1.0, 0.0, None, None, "")


@pytest.mark.parametrize("hw,hh", [(0.9, 0.9), (0, 0), (-0.1, -0.1), ("big", "big"), (None, None)])
def test_ws_lock_ignores_out_of_range_box_sizes(ws_client, fake_manager, hw, hh):
    """A box half-size outside (0, 0.5] falls back to the default box instead of being trusted."""
    tc, _ = ws_client
    with tc.websocket_connect(f"{URL}?source=0&ticket=t") as ws:
        _receive(ws, "receive_bytes")
        ws.send_text(json.dumps({"cmd": "lock", "x": 0.5, "y": 0.5, "hw": hw, "hh": hh}))
    q = fake_manager.holder["queue"]
    fake_manager.lock_object.assert_called_once_with("0", q, 0.5, 0.5, None, None, "")


@pytest.mark.parametrize("payload", [
    {"cmd": "lock"},                                   # no coordinates
    {"cmd": "lock", "x": "0.5", "y": "0.5"},           # strings, not numbers
    {"cmd": "lock", "x": None, "y": 0.5},
    {"cmd": "lock", "x": 0.5},
])
def test_ws_lock_with_invalid_coordinates_is_ignored(ws_client, fake_manager, payload):
    tc, _ = ws_client
    with tc.websocket_connect(f"{URL}?source=0&ticket=t") as ws:
        _receive(ws, "receive_bytes")
        ws.send_text(json.dumps(payload))
    fake_manager.lock_object.assert_not_called()


def test_ws_name_and_unlock_commands(ws_client, fake_manager):
    tc, _ = ws_client
    with tc.websocket_connect(f"{URL}?source=0&ticket=t") as ws:
        _receive(ws, "receive_bytes")
        ws.send_text(json.dumps({"cmd": "name", "name": "ALPHA"}))
        ws.send_text(json.dumps({"cmd": "name"}))               # missing name -> cleared
        ws.send_text(json.dumps({"cmd": "unlock"}))
    q = fake_manager.holder["queue"]
    assert fake_manager.name_object.call_args_list[0].args == ("0", q, "ALPHA")
    assert fake_manager.name_object.call_args_list[1].args == ("0", q, "")
    fake_manager.unlock_object.assert_called_once_with("0", q)


@pytest.mark.parametrize("raw", [
    "not json at all",
    "[1, 2, 3]",                                         # JSON but not an object
    "42",
    "null",
    json.dumps({"cmd": "explode"}),                       # unknown command
    json.dumps({"no_cmd": True}),
])
def test_ws_malformed_or_unknown_messages_are_ignored_and_stream_stays_open(ws_client, fake_manager, raw):
    tc, _ = ws_client
    with tc.websocket_connect(f"{URL}?source=0&ticket=t") as ws:
        _receive(ws, "receive_bytes")
        ws.send_text(raw)
        ws.send_text(json.dumps({"cmd": "unlock"}))      # a later valid command still works
    fake_manager.lock_object.assert_not_called()
    fake_manager.unlock_object.assert_called_once()


def test_ws_source_is_trimmed_for_the_shared_session_key(ws_client, fake_manager):
    tc, _ = ws_client
    with tc.websocket_connect(f"{URL}?source=%200%20&ticket=t") as ws:      # " 0 "
        _receive(ws, "receive_bytes")
    fake_manager.unsubscribe.assert_called_once()
    assert fake_manager.unsubscribe.call_args.args[0] == "0"
