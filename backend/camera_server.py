"""
Standalone native payload-camera server.

Runs OUTSIDE Docker so OpenCV can open the machine's real webcam — the
Dockerized backend cannot (Docker Desktop for Windows has no host-webcam
passthrough). This is the only piece of the app that needs to run natively;
everything else stays in Docker as usual. IP/RTSP camera sources work
identically here and in the Dockerized backend's own camera-stream route,
since those are plain network streams, not local devices.

Reuses app.modules.drone_control.payload_camera (pure OpenCV + structlog,
no other app dependency) so the capture/reconnect logic isn't duplicated.

Usage (from the backend/ directory):
    .venv_native_py313/Scripts/python.exe camera_server.py
Or via run_native.ps1, which also sets SECRET_KEY from the repo .env so
tokens minted by the main (Dockerized) backend validate here too.
"""
import asyncio
import importlib.util
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt

# Import payload_camera.py directly by path rather than through the
# app.modules.drone_control package — that package's __init__.py eagerly
# imports sibling modules (data_recorder, mavlink_manager, ...) that need
# sqlalchemy/pymavlink/etc., which this standalone server doesn't install.
# Registering it in sys.modules before exec is required: @dataclass looks
# its own module up there, and fails on a module that isn't registered.
_spec = importlib.util.spec_from_file_location(
    "payload_camera",
    Path(__file__).parent / "app" / "modules" / "drone_control" / "payload_camera.py",
)
_payload_camera = importlib.util.module_from_spec(_spec)
sys.modules["payload_camera"] = _payload_camera
_spec.loader.exec_module(_payload_camera)
payload_camera_manager = _payload_camera.payload_camera_manager

SECRET_KEY = os.environ.get("SECRET_KEY", "please-change-this-secret-key-in-production")
ALGORITHM = "HS256"

app = FastAPI(title="DroneArjuna Native Camera Server")


def _check_token(token: str) -> None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if not payload.get("sub"):
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.websocket("/api/drone-control/camera-stream")
async def camera_stream(ws: WebSocket, source: str = Query(...), token: str = Query(...)):
    try:
        _check_token(token)
    except HTTPException:
        await ws.close(code=4401)
        return

    await ws.accept()
    loop = asyncio.get_event_loop()
    queue, key = payload_camera_manager.subscribe(source, loop)

    async def _sender():
        try:
            while True:
                frame = await queue.get()
                await ws.send_bytes(frame)
        except Exception:
            pass

    async def _receiver():
        try:
            while True:
                await ws.receive_text()
        except (WebSocketDisconnect, Exception):
            pass

    sender_task = asyncio.create_task(_sender())
    receiver_task = asyncio.create_task(_receiver())

    await asyncio.wait({sender_task, receiver_task}, return_when=asyncio.FIRST_COMPLETED)

    sender_task.cancel()
    receiver_task.cancel()
    payload_camera_manager.unsubscribe(key, queue)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
