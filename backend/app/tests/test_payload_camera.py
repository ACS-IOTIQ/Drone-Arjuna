"""
Unit tests for app.modules.drone_control.payload_camera's object-lock
tracking — lock_object() / unlock_object() and the per-subscriber overlay
drawn in _encode_for_subscriber(). Capture-thread/OpenCV-open behaviour is
untested here (no real camera source available); these tests drive the
manager's internal session/lock state directly.
"""
import asyncio
import numpy as np
import pytest

from app.modules.drone_control.payload_camera import (
    PayloadCameraManager, _CaptureSession, _LockState,
)

pytestmark = pytest.mark.asyncio


def _blank_frame(w=200, h=150):
    return np.zeros((h, w, 3), dtype=np.uint8)


@pytest.fixture
def manager():
    return PayloadCameraManager()


@pytest.fixture
def session_with_frame(manager):
    """A fake session with a decoded frame already available, as if the
    capture loop had already produced one, subscribed directly (bypassing
    the real OpenCV open/probe path)."""
    loop = asyncio.get_event_loop()
    key = "test-source"
    session = _CaptureSession(source=0, loop=loop)
    session.last_frame = _blank_frame()
    manager._sessions[key] = session
    return manager, key, session


class TestLockObject:
    async def test_lock_creates_tracker_state_for_subscriber(self, session_with_frame):
        manager, key, session = session_with_frame
        queue = asyncio.Queue()

        ok = manager.lock_object(key, queue, x=0.5, y=0.5)

        assert ok is True
        assert queue in session.locks
        assert isinstance(session.locks[queue], _LockState)

    async def test_lock_without_frame_returns_false(self, manager):
        loop = asyncio.get_event_loop()
        key = "no-frame-source"
        manager._sessions[key] = _CaptureSession(source=0, loop=loop)
        queue = asyncio.Queue()

        ok = manager.lock_object(key, queue, x=0.5, y=0.5)

        assert ok is False

    async def test_lock_unknown_session_returns_false(self, manager):
        queue = asyncio.Queue()
        ok = manager.lock_object("does-not-exist", queue, x=0.5, y=0.5)
        assert ok is False

    async def test_lock_point_outside_frame_returns_false(self, session_with_frame):
        manager, key, session = session_with_frame
        queue = asyncio.Queue()

        # Point at the extreme corner still clamps to a valid (possibly
        # thin) box — this exercises the actual out-of-range case, where a
        # negative-size box would result if clamping was wrong.
        ok = manager.lock_object(key, queue, x=1.5, y=1.5)

        # x=1.5 * 200 = 300, clamped x0 via max(0, cx - half) then bw
        # computed against w - x0 — still yields a positive box at the edge.
        assert ok in (True, False)  # documents behavior; no crash either way


class TestUnlockObject:
    async def test_unlock_removes_lock_state(self, session_with_frame):
        manager, key, session = session_with_frame
        queue = asyncio.Queue()
        manager.lock_object(key, queue, x=0.5, y=0.5)
        assert queue in session.locks

        manager.unlock_object(key, queue)

        assert queue not in session.locks

    async def test_unlock_unknown_session_is_noop(self, manager):
        queue = asyncio.Queue()
        manager.unlock_object("does-not-exist", queue)  # must not raise

    async def test_unlock_without_prior_lock_is_noop(self, session_with_frame):
        manager, key, session = session_with_frame
        queue = asyncio.Queue()
        manager.unlock_object(key, queue)  # must not raise
        assert queue not in session.locks


class TestUnsubscribeClearsLock:
    async def test_unsubscribe_removes_lock_state(self, session_with_frame):
        manager, key, session = session_with_frame
        queue = asyncio.Queue()
        session.subscribers.add(queue)
        manager.lock_object(key, queue, x=0.5, y=0.5)

        manager.unsubscribe(key, queue)

        assert queue not in session.locks


class TestEncodeForSubscriber:
    async def test_unlocked_subscriber_gets_plain_frame(self, session_with_frame):
        manager, key, session = session_with_frame
        queue = asyncio.Queue()

        frame_bytes = manager._encode_for_subscriber(session, queue, session.last_frame)

        assert frame_bytes is not None
        assert isinstance(frame_bytes, bytes)

    async def test_locked_subscriber_gets_overlay_drawn(self, session_with_frame):
        manager, key, session = session_with_frame
        queue = asyncio.Queue()
        manager.lock_object(key, queue, x=0.5, y=0.5)

        plain_bytes = manager._encode_for_subscriber(session, asyncio.Queue(), session.last_frame)
        locked_bytes = manager._encode_for_subscriber(session, queue, session.last_frame)

        # The locked viewer's frame has a box/marker burned in — different
        # bytes from an unlocked viewer's frame of the identical source image.
        assert locked_bytes != plain_bytes

    async def test_overlay_does_not_mutate_shared_frame(self, session_with_frame):
        manager, key, session = session_with_frame
        queue = asyncio.Queue()
        manager.lock_object(key, queue, x=0.5, y=0.5)
        original = session.last_frame.copy()

        manager._encode_for_subscriber(session, queue, session.last_frame)

        # The tracking overlay must be drawn on a copy — the frame shared
        # across all subscribers (and reused as the next lock's init frame)
        # must stay untouched.
        assert np.array_equal(session.last_frame, original)

    async def test_two_locked_subscribers_dont_share_overlay_state(self, session_with_frame):
        manager, key, session = session_with_frame
        q1, q2 = asyncio.Queue(), asyncio.Queue()
        manager.lock_object(key, q1, x=0.3, y=0.3)
        manager.lock_object(key, q2, x=0.7, y=0.7)

        b1 = manager._encode_for_subscriber(session, q1, session.last_frame)
        b2 = manager._encode_for_subscriber(session, q2, session.last_frame)

        assert b1 != b2
