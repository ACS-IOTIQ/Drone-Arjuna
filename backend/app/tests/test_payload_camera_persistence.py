"""
The operator's lock box and its name must never disappear from the video:
  - tracker unavailable at lock time  -> box + name held at the drawn position
  - tracker raising while updating    -> box + name kept (red, TARGET LOST), stream survives
  - name set on the lock / via name_object is burned in on every frame
"""
import asyncio

import cv2
import numpy as np
import pytest

from app.modules.drone_control import payload_camera as pc
from app.modules.drone_control.payload_camera import PayloadCameraManager, _CaptureSession

pytestmark = pytest.mark.asyncio


def _frame(w=320, h=240):
    return np.full((h, w, 3), 40, dtype=np.uint8)


def _decode(jpeg: bytes) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)


def _amber_pixels(img: np.ndarray) -> int:
    # TRACKER_BOX_COLOR is BGR (0,165,255); JPEG blurs it, so use a tolerance
    target = np.array(pc.TRACKER_BOX_COLOR, dtype=np.int16)
    return int((np.abs(img.astype(np.int16) - target).sum(axis=2) < 90).sum())


def _red_pixels(img: np.ndarray) -> int:
    return int(((img[:, :, 2] > 200) & (img[:, :, 1] < 60) & (img[:, :, 0] < 60)).sum())


@pytest.fixture
def setup():
    manager = PayloadCameraManager()
    session = _CaptureSession(source=0, loop=asyncio.get_event_loop())
    session.last_frame = _frame()
    manager._sessions["cam"] = session
    return manager, session


class _BrokenInit:
    def init(self, *a, **k):
        raise RuntimeError("tracking module missing")


class _BrokenUpdate:
    def init(self, *a, **k):
        return True

    def update(self, *a, **k):
        raise RuntimeError("frame size changed")


class _AlwaysLost:
    def init(self, *a, **k):
        return True

    def update(self, *a, **k):
        return False, (0, 0, 0, 0)


async def test_box_and_name_held_when_tracker_cannot_start(setup, monkeypatch):
    manager, session = setup
    monkeypatch.setattr(pc, "_new_tracker", lambda: _BrokenInit())
    q = asyncio.Queue()

    ok = manager.lock_object("cam", q, x=0.5, y=0.5, hw=0.1, hh=0.1, name="TARGET-1")

    assert ok is True                                   # the lock is accepted, not dropped
    assert session.locks[q].tracker is None
    img = _decode(manager._encode_for_subscriber(session, q, session.last_frame))
    assert _amber_pixels(img) > 200                     # amber box + name chip drawn
    assert _red_pixels(img) == 0                        # not shown as "lost"


async def test_held_box_is_identical_on_every_frame(setup, monkeypatch):
    manager, session = setup
    monkeypatch.setattr(pc, "_new_tracker", lambda: _BrokenInit())
    q = asyncio.Queue()
    manager.lock_object("cam", q, x=0.5, y=0.5, hw=0.1, hh=0.1, name="A")
    first = manager._encode_for_subscriber(session, q, session.last_frame)
    for _ in range(5):
        assert manager._encode_for_subscriber(session, q, _frame()) == first


async def test_tracker_error_does_not_raise_and_keeps_box_and_name(setup, monkeypatch):
    manager, session = setup
    monkeypatch.setattr(pc, "_new_tracker", lambda: _BrokenUpdate())
    q = asyncio.Queue()
    manager.lock_object("cam", q, x=0.5, y=0.5, hw=0.1, hh=0.1, name="TARGET-1")

    data = manager._encode_for_subscriber(session, q, session.last_frame)   # must not raise

    assert data is not None
    img = _decode(data)
    assert _red_pixels(img) > 100                       # last box kept, shown as lost
    assert session.locks[q].lost is True


async def test_lost_target_keeps_the_named_box_on_screen(setup, monkeypatch):
    manager, session = setup
    monkeypatch.setattr(pc, "_new_tracker", lambda: _AlwaysLost())
    q = asyncio.Queue()
    manager.lock_object("cam", q, x=0.5, y=0.5, hw=0.1, hh=0.1, name="TARGET-1")
    for _ in range(10):                                  # many frames with no confident match
        img = _decode(manager._encode_for_subscriber(session, q, session.last_frame))
        assert _red_pixels(img) > 100                    # box (and chip) never vanish


async def test_name_is_burned_in_and_can_be_changed(setup, monkeypatch):
    manager, session = setup
    monkeypatch.setattr(pc, "_new_tracker", lambda: _BrokenInit())
    q_named, q_plain = asyncio.Queue(), asyncio.Queue()
    manager.lock_object("cam", q_named, x=0.5, y=0.5, hw=0.1, hh=0.1, name="ALPHA")
    manager.lock_object("cam", q_plain, x=0.5, y=0.5, hw=0.1, hh=0.1, name="")

    named = manager._encode_for_subscriber(session, q_named, session.last_frame)
    plain = manager._encode_for_subscriber(session, q_plain, session.last_frame)
    assert named != plain                                # the label chip is really drawn

    manager.name_object("cam", q_plain, "ALPHA")         # naming later (the "N"/"E" keys)
    renamed = manager._encode_for_subscriber(session, q_plain, session.last_frame)
    assert renamed == named


async def test_stream_survives_tracker_failure_across_many_frames(setup, monkeypatch):
    """The capture thread calls _push -> _encode for every frame; none may raise."""
    manager, session = setup
    monkeypatch.setattr(pc, "_new_tracker", lambda: _BrokenUpdate())
    q = asyncio.Queue()
    manager.lock_object("cam", q, x=0.5, y=0.5, name="X")
    for _ in range(20):
        assert manager._encode_for_subscriber(session, q, _frame()) is not None
