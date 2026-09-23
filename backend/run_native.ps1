# ══════════════════════════════════════════════════════════════════
# run_native.ps1 — Run the payload-camera server natively on Windows
#
# Why: cv2.VideoCapture(0) inside the Dockerized backend can never see the
# host's webcam — Docker Desktop for Windows has no device passthrough for
# it. This script runs camera_server.py, a small standalone FastAPI app
# with no dependency on the rest of the stack, directly on Windows so
# OpenCV can open the real webcam. Everything else (Postgres, Redis,
# RabbitMQ, MinIO, the main backend, etc.) keeps running in Docker as
# usual via `docker compose up -d`.
#
# It listens on port 8001 (the Dockerized backend keeps 8000) and shares
# the same SECRET_KEY, so a login token from the normal (Dockerized)
# backend is accepted here too — the frontend's /camera-api proxy path
# routes to this server, everything else keeps going through /api to the
# Dockerized backend.
#
# Usage:
#   cd backend
#   .\run_native.ps1
# ══════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"

# Pull SECRET_KEY from the repo's .env so it isn't duplicated anywhere.
$envFile = Join-Path $PSScriptRoot "..\.env"
$secretKey = "please-change-this-secret-key-in-production"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*SECRET_KEY\s*=\s*(.*)\s*$') { $secretKey = $matches[1] }
    }
}
$env:SECRET_KEY = $secretKey

$venvPython = Join-Path $PSScriptRoot ".venv_native_py313\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating native venv (.venv_native_py313)..." -ForegroundColor Yellow
    python -m venv "$PSScriptRoot\.venv_native_py313"
    & $venvPython -m pip install -q --upgrade pip
    & $venvPython -m pip install -q fastapi "uvicorn[standard]" "python-jose[cryptography]" opencv-python-headless structlog python-dotenv
}

Write-Host "Starting native camera server on :8001 -- webcam index 0 opens this machine's real camera." -ForegroundColor Cyan
& $venvPython (Join-Path $PSScriptRoot "camera_server.py")
