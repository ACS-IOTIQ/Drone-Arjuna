"""
System events WebSocket route tests
===================================
WS /api/system/events

The single channel the browser opens at start-up to receive backend-initiated notices
(DATA_LOSS_DETECTED, DATA_RESTORED, BACKUP_MISSING, ...). Message construction and the
queue fan-out are covered in test_system_events.py; this file covers the socket route.

Covers:
  - auth: no ticket / bad ticket / insufficient role all close with 4401 before accept
    (a JWT in the query string is not accepted)
  - delivery: a broadcast reaches every connected client as JSON text, in order, with
    the extra fields
  - subscriber bookkeeping: registered on connect, removed on disconnect
  - messages sent by the client are consumed and ignored; the stream stays open
  - a subscriber marked stale (queue overflow) is closed so the browser reconnects
    and starts fresh; broadcast flags a full queue's owner as stale
  - idle connections are dropped after the receive timeout
"""
import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core import system_events

URL = "/api/system/events"


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


@pytest.fixture(autouse=True)
def _clean_state():
    system_events._subscribers.clear()
    system_events._subscriber_stale.clear()
    yield
    system_events._subscribers.clear()
    system_events._subscriber_stale.clear()


@pytest.fixture
def tc(monkeypatch):
    """TestClient on the real app with no startup side effects and no DB access."""
    from app.main import app

    @asynccontextmanager
    async def _noop_lifespan(a):
        yield

    @asynccontextmanager
    async def _no_db():
        yield MagicMock()

    original = app.router.lifespan_context
    app.router.lifespan_context = _noop_lifespan
    monkeypatch.setattr(system_events, "AsyncSessionLocal", _no_db)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.router.lifespan_context = original


@pytest.fixture
def authed(monkeypatch):
    """Make the ticket check succeed; returns the mock so tests can inspect the call."""
    auth = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(system_events, "authenticate_ws", auth)
    return auth


def _wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _broadcast(tc, event_type, message, **extra):
    """Run broadcast_system_event on the app's event loop (where the subscriber queues live)."""
    tc.portal.call(lambda: system_events.broadcast_system_event(event_type, message, **extra))


# ══════════════════════════════════════════════════════════════════════
# Authentication
# ══════════════════════════════════════════════════════════════════════

def test_connection_without_a_ticket_is_closed_4401(tc):
    with pytest.raises(WebSocketDisconnect) as exc:
        with tc.websocket_connect(URL):
            pass
    assert exc.value.code == 4401
    assert system_events._subscribers == []


def test_jwt_in_the_query_string_is_not_accepted(tc):
    with pytest.raises(WebSocketDisconnect) as exc:
        with tc.websocket_connect(f"{URL}?token=eyJhbGciOi.fake.jwt"):
            pass
    assert exc.value.code == 4401


@pytest.mark.parametrize("status", [401, 403])
def test_any_auth_failure_closes_with_4401(tc, monkeypatch, status):
    monkeypatch.setattr(
        system_events, "authenticate_ws",
        AsyncMock(side_effect=HTTPException(status_code=status, detail="nope")),
    )
    with pytest.raises(WebSocketDisconnect) as exc:
        with tc.websocket_connect(f"{URL}?ticket=bad"):
            pass
    assert exc.value.code == 4401
    assert system_events._subscribers == []


def test_viewer_role_is_enough_to_listen(tc, authed):
    with tc.websocket_connect(f"{URL}?ticket=t"):
        pass
    assert authed.await_args.kwargs["min_role"] == "viewer"


# ══════════════════════════════════════════════════════════════════════
# Delivery
# ══════════════════════════════════════════════════════════════════════

def test_broadcast_reaches_a_connected_client_as_json_text(tc, authed):
    with tc.websocket_connect(f"{URL}?ticket=t") as ws:
        assert _wait_for(lambda: len(system_events._subscribers) == 1)
        _broadcast(tc, "DATA_RESTORED", "Database restored from backup.", dump_file="dump_1.json")
        payload = json.loads(_receive(ws))
    assert payload["type"] == "DATA_RESTORED"
    assert payload["message"] == "Database restored from backup."
    assert payload["dump_file"] == "dump_1.json"
    assert "timestamp" in payload


def test_events_arrive_in_the_order_they_were_broadcast(tc, authed):
    with tc.websocket_connect(f"{URL}?ticket=t") as ws:
        assert _wait_for(lambda: len(system_events._subscribers) == 1)
        for name in ("DATA_LOSS_DETECTED", "DATA_RESTORED", "BACKUP_MISSING"):
            _broadcast(tc, name, "m")
        types = [json.loads(_receive(ws))["type"] for _ in range(3)]
    assert types == ["DATA_LOSS_DETECTED", "DATA_RESTORED", "BACKUP_MISSING"]


def test_every_connected_client_gets_the_event(tc, authed):
    with tc.websocket_connect(f"{URL}?ticket=a") as first, tc.websocket_connect(f"{URL}?ticket=b") as second:
        assert _wait_for(lambda: len(system_events._subscribers) == 2)
        _broadcast(tc, "DATA_RESTORED", "ok")
        assert json.loads(_receive(first))["type"] == "DATA_RESTORED"
        assert json.loads(_receive(second))["type"] == "DATA_RESTORED"


def test_a_client_only_sees_events_broadcast_after_it_connected(tc, authed):
    _broadcast(tc, "OLD_EVENT", "before anyone connected")
    with tc.websocket_connect(f"{URL}?ticket=t") as ws:
        assert _wait_for(lambda: len(system_events._subscribers) == 1)
        _broadcast(tc, "NEW_EVENT", "after")
        assert json.loads(_receive(ws))["type"] == "NEW_EVENT"      # no replay of OLD_EVENT


# ══════════════════════════════════════════════════════════════════════
# Subscriber bookkeeping
# ══════════════════════════════════════════════════════════════════════

def test_subscriber_is_registered_while_connected_and_removed_after(tc, authed):
    with tc.websocket_connect(f"{URL}?ticket=t"):
        assert _wait_for(lambda: len(system_events._subscribers) == 1)
        assert len(system_events._subscriber_stale) == 1
    assert _wait_for(lambda: system_events._subscribers == [])
    assert _wait_for(lambda: system_events._subscriber_stale == {})


def test_one_clients_disconnect_does_not_affect_the_other(tc, authed):
    with tc.websocket_connect(f"{URL}?ticket=keep") as keeper:
        with tc.websocket_connect(f"{URL}?ticket=leave"):
            assert _wait_for(lambda: len(system_events._subscribers) == 2)
        assert _wait_for(lambda: len(system_events._subscribers) == 1)
        _broadcast(tc, "STILL_HERE", "m")
        assert json.loads(_receive(keeper))["type"] == "STILL_HERE"


def test_broadcast_after_everyone_left_is_harmless(tc, authed):
    with tc.websocket_connect(f"{URL}?ticket=t"):
        assert _wait_for(lambda: len(system_events._subscribers) == 1)
    assert _wait_for(lambda: system_events._subscribers == [])
    _broadcast(tc, "NOBODY_LISTENING", "m")                               # must not raise


# ══════════════════════════════════════════════════════════════════════
# Client messages
# ══════════════════════════════════════════════════════════════════════

def test_client_messages_are_ignored_and_the_stream_stays_open(tc, authed):
    with tc.websocket_connect(f"{URL}?ticket=t") as ws:
        assert _wait_for(lambda: len(system_events._subscribers) == 1)
        ws.send_text("ping")
        ws.send_text(json.dumps({"cmd": "anything"}))
        _broadcast(tc, "AFTER_CLIENT_CHATTER", "m")
        assert json.loads(_receive(ws))["type"] == "AFTER_CLIENT_CHATTER"


# ══════════════════════════════════════════════════════════════════════
# Stale subscribers & idle timeout
# ══════════════════════════════════════════════════════════════════════

def test_a_stale_subscriber_is_closed_so_the_browser_reconnects(tc, authed):
    async def _mark_all_stale():
        for event in system_events._subscriber_stale.values():
            event.set()

    with tc.websocket_connect(f"{URL}?ticket=t") as ws:
        assert _wait_for(lambda: len(system_events._subscribers) == 1)
        tc.portal.call(_mark_all_stale)
        with pytest.raises(WebSocketDisconnect):
            _receive(ws)
    assert _wait_for(lambda: system_events._subscribers == [])
    assert _wait_for(lambda: system_events._subscriber_stale == {})


def test_idle_connection_is_dropped_after_the_receive_timeout(tc, authed, monkeypatch):
    """The route gives up on a client that sends nothing for 60 s (shortened here)."""
    real_wait_for = asyncio.wait_for

    async def _fast_wait_for(awaitable, timeout=None):
        return await real_wait_for(awaitable, timeout=0.2 if timeout == 60.0 else timeout)

    monkeypatch.setattr(asyncio, "wait_for", _fast_wait_for)
    with tc.websocket_connect(f"{URL}?ticket=t"):
        assert _wait_for(lambda: len(system_events._subscribers) == 1)
        # No events and no client traffic: the receiver times out and the route cleans up.
        # NOTE: do not call ws.receive_*() here. When the route simply returns (no explicit
        # close frame) Starlette's TestClient never delivers a message, so a receive would
        # block the whole test run forever. Assert the server-side effect instead.
        assert _wait_for(lambda: system_events._subscribers == [], timeout=5.0)
        assert _wait_for(lambda: system_events._subscriber_stale == {}, timeout=5.0)


# ══════════════════════════════════════════════════════════════════════
# broadcast_system_event — overflow handling (no socket needed)
# ══════════════════════════════════════════════════════════════════════

async def test_full_queue_flags_its_subscriber_as_stale():
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait("already-full")
    stale = asyncio.Event()
    system_events._subscribers.append(queue)
    system_events._subscriber_stale[id(queue)] = stale

    await system_events.broadcast_system_event("EVT", "msg")

    assert stale.is_set()
    assert queue.qsize() == 1 and queue.get_nowait() == "already-full"      # nothing was dropped silently


async def test_healthy_queue_is_not_flagged_stale():
    queue = asyncio.Queue(maxsize=5)
    stale = asyncio.Event()
    system_events._subscribers.append(queue)
    system_events._subscriber_stale[id(queue)] = stale

    await system_events.broadcast_system_event("EVT", "msg")

    assert not stale.is_set()
    assert queue.qsize() == 1


async def test_only_the_slow_subscriber_is_flagged():
    slow, fast = asyncio.Queue(maxsize=1), asyncio.Queue(maxsize=5)
    slow.put_nowait("already-full")
    slow_stale, fast_stale = asyncio.Event(), asyncio.Event()
    system_events._subscribers.extend([slow, fast])
    system_events._subscriber_stale[id(slow)] = slow_stale
    system_events._subscriber_stale[id(fast)] = fast_stale

    await system_events.broadcast_system_event("EVT", "msg")

    assert slow_stale.is_set() and not fast_stale.is_set()
    assert fast.qsize() == 1                                                # the fast one still got it


async def test_full_queue_without_a_stale_entry_does_not_raise():
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait("already-full")
    system_events._subscribers.append(queue)                                # no _subscriber_stale entry
    await system_events.broadcast_system_event("EVT", "msg")
