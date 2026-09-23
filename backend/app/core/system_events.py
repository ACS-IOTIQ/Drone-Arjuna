"""
System-wide event broadcast — a single WebSocket channel the frontend opens
once at app start to receive backend-initiated notices (e.g. "database was
auto-restored from backup") that aren't tied to any one drone or mission.

Kept separate from the RabbitMQ event bus (app.core.events) since these are
purely for driving UI toasts/refetches in the connected browser tab, not
inter-module or inter-process communication.
"""
import asyncio
import json
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.database import AsyncSessionLocal
from app.core.auth import get_current_user_from_token

log = structlog.get_logger()
router = APIRouter()

_subscribers: list[asyncio.Queue] = []
# One cancel-event per subscriber queue, used to force-close a subscriber
# that has fallen behind (see broadcast_system_event) instead of silently
# dropping its events forever with no signal that it missed anything.
_subscriber_stale: dict[int, asyncio.Event] = {}


async def broadcast_system_event(event_type: str, message: str, **extra):
    payload = json.dumps({
        "type": event_type,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **extra,
    }, default=str)
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            # A full queue means this subscriber's sender has fallen far
            # enough behind that it may have already missed prior events
            # (e.g. DATA_LOSS_DETECTED without the matching DATA_RESTORED) —
            # silently continuing to drop would leave it permanently out of
            # sync with no signal. Force it to reconnect instead: the
            # frontend's WebSocket auto-reconnects on close and starts fresh.
            log.warning("System event subscriber queue full — forcing reconnect")
            stale_event = _subscriber_stale.get(id(q))
            if stale_event is not None:
                stale_event.set()


@router.websocket("/events")
async def system_events_stream(ws: WebSocket, token: str = Query(...)):
    """
    Browsers can't attach an Authorization header to a WebSocket handshake,
    so the access token is passed as a query parameter instead and validated
    the same way as the Bearer token on REST routes (see the camera-stream
    WebSocket route for the identical pattern).
    """
    async with AsyncSessionLocal() as db:
        try:
            await get_current_user_from_token(token, db)
        except HTTPException:
            await ws.close(code=4401)
            return

    await ws.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=20)
    stale = asyncio.Event()
    _subscribers.append(queue)
    _subscriber_stale[id(queue)] = stale

    async def _sender():
        try:
            while True:
                text = await queue.get()
                await ws.send_text(text)
        except Exception:
            pass

    async def _receiver():
        try:
            while True:
                await asyncio.wait_for(ws.receive_text(), timeout=60.0)
        except (WebSocketDisconnect, asyncio.TimeoutError, Exception):
            pass

    async def _stale_watch():
        await stale.wait()

    sender_task = asyncio.create_task(_sender())
    receiver_task = asyncio.create_task(_receiver())
    stale_task = asyncio.create_task(_stale_watch())
    await asyncio.wait(
        {sender_task, receiver_task, stale_task}, return_when=asyncio.FIRST_COMPLETED
    )

    sender_task.cancel()
    receiver_task.cancel()
    stale_task.cancel()
    if queue in _subscribers:
        _subscribers.remove(queue)
    _subscriber_stale.pop(id(queue), None)
    if stale.is_set():
        try:
            await ws.close()
        except Exception:
            pass
