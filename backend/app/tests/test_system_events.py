"""
Unit tests for app.core.system_events — the WebSocket broadcast channel used
for backend-initiated UI notices (e.g. "database was auto-restored").
"""
import asyncio
import json

import pytest

from app.core import system_events


@pytest.fixture(autouse=True)
def _clean_subscribers():
    """Each test starts with no leaked subscriber queues."""
    system_events._subscribers.clear()
    yield
    system_events._subscribers.clear()


class TestBroadcastSystemEvent:
    async def test_no_subscribers_does_not_raise(self):
        await system_events.broadcast_system_event("PING", "hello")

    async def test_single_subscriber_receives_payload(self):
        queue = asyncio.Queue(maxsize=10)
        system_events._subscribers.append(queue)

        await system_events.broadcast_system_event("DATA_RESTORED", "restored ok", dump_file="x.json")

        assert queue.qsize() == 1
        payload = json.loads(queue.get_nowait())
        assert payload["type"] == "DATA_RESTORED"
        assert payload["message"] == "restored ok"
        assert payload["dump_file"] == "x.json"
        assert "timestamp" in payload

    async def test_multiple_subscribers_all_receive(self):
        q1, q2 = asyncio.Queue(maxsize=10), asyncio.Queue(maxsize=10)
        system_events._subscribers.extend([q1, q2])

        await system_events.broadcast_system_event("EVT", "msg")

        assert q1.qsize() == 1
        assert q2.qsize() == 1

    async def test_full_queue_is_silently_skipped(self):
        queue = asyncio.Queue(maxsize=1)
        queue.put_nowait("already-full")
        system_events._subscribers.append(queue)

        # Must not raise even though the queue is at capacity
        await system_events.broadcast_system_event("EVT", "msg")

        assert queue.qsize() == 1
        assert queue.get_nowait() == "already-full"

    async def test_extra_kwargs_are_serialized_into_payload(self):
        queue = asyncio.Queue(maxsize=10)
        system_events._subscribers.append(queue)

        await system_events.broadcast_system_event("EVT", "msg", foo="bar", count=3)

        payload = json.loads(queue.get_nowait())
        assert payload["foo"] == "bar"
        assert payload["count"] == 3

    async def test_non_serializable_extra_is_stringified(self):
        queue = asyncio.Queue(maxsize=10)
        system_events._subscribers.append(queue)

        class Weird:
            def __str__(self):
                return "weird-repr"

        await system_events.broadcast_system_event("EVT", "msg", obj=Weird())

        payload = json.loads(queue.get_nowait())
        assert payload["obj"] == "weird-repr"
