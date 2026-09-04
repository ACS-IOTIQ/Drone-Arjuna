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
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = structlog.get_logger()
router = APIRouter()

_subscribers: list[asyncio.Queue] = []


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
            pass


@router.websocket("/events")
async def system_events_stream(ws: WebSocket):
    await ws.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=20)
    _subscribers.append(queue)

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

    sender_task = asyncio.create_task(_sender())
    receiver_task = asyncio.create_task(_receiver())
    await asyncio.wait({sender_task, receiver_task}, return_when=asyncio.FIRST_COMPLETED)

    sender_task.cancel()
    receiver_task.cancel()
    if queue in _subscribers:
        _subscribers.remove(queue)
