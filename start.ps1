#Requires -Version 5.1
<#
.SYNOPSIS
    DroneArjuna GCS — full-stack launcher.

.DESCRIPTION
    Starts com_bridge.py (Windows-side COM-to-TCP bridge) in a background
    window, then brings up the Docker Compose stack.

    com_bridge.py MUST run on the Windows host — it needs direct access to
    Windows COM ports which Docker containers cannot reach.  The bridge
    exposes the serial device over TCP on port 5762 (discoverable on 5761)
    so the backend container can read it via host.docker.internal.

.PARAMETER ComPort
    COM port to forward, e.g. COM3.  Defaults to "auto" (picks the first
    USB-serial device found).

.PARAMETER Baud
    Baud rate for the serial port.  Default 115200 (USB direct Pixhawk).
    Use 57600 for SiK telemetry radios.

.PARAMETER Build
    Pass -Build to force a Docker image rebuild (same as --build flag).

.EXAMPLE
    .\start.ps1                   # auto port, 115200 baud, no rebuild
    .\start.ps1 -Build            # auto port, force rebuild
    .\start.ps1 -ComPort COM4 -Baud 57600
#>
param(
    [string]$ComPort = "auto",
    [int]$Baud       = 115200,
    [switch]$Build
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── 1. Locate com_bridge.py ──────────────────────────────────────────────────

$BridgeScript = Join-Path $ScriptDir "com_bridge.py"
if (-not (Test-Path $BridgeScript)) {
    # Fall back to sub-directory location
    $BridgeScript = Join-Path $ScriptDir "com_bridge\com_bridge.py"
}
if (-not (Test-Path $BridgeScript)) {
    Write-Error "com_bridge.py not found under $ScriptDir"
    exit 1
}

# ── 2. Kill any stale com_bridge process from a previous run ─────────────────

$stale = Get-WmiObject Win32_Process -Filter "Name='python.exe' OR Name='python3.exe'" |
         Where-Object { $_.CommandLine -like "*com_bridge.py*" }
if ($stale) {
    Write-Host "[launcher] Stopping stale com_bridge.py (PID $($stale.ProcessId))..." -ForegroundColor Yellow
    $stale | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 500
}

# ── 3. Start com_bridge.py in a separate, visible console window ─────────────

$bridgeArgs = "`"$BridgeScript`" $ComPort $Baud"
Write-Host "[launcher] Starting com_bridge.py  (port=$ComPort  baud=$Baud)" -ForegroundColor Cyan

$bridgeProc = Start-Process `
    -FilePath   "python" `
    -ArgumentList $bridgeArgs `
    -WorkingDirectory $ScriptDir `
    -PassThru

# Give the bridge a moment to open the serial port and bind TCP 5762/5761
Write-Host "[launcher] Waiting 3 s for bridge to initialise..." -ForegroundColor DarkGray
Start-Sleep -Seconds 3

# Quick health check — probe the discovery endpoint
try {
    $status = Invoke-RestMethod -Uri "http://localhost:5761/ports" -TimeoutSec 2
    if ($status.connected) {
        Write-Host "[launcher] Bridge ready — $($status.active_port) @ $($status.baud) baud -> TCP:$($status.tcp_port)" -ForegroundColor Green
    } else {
        Write-Host "[launcher] Bridge running but no serial device detected yet (will retry when plugged in)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "[launcher] Bridge discovery endpoint not responding — continuing anyway" -ForegroundColor Yellow
}

# ── 4. Start Docker Compose ──────────────────────────────────────────────────

Set-Location $ScriptDir

$composeArgs = @("compose", "up", "-d")
if ($Build) { $composeArgs += "--build" }

Write-Host ""
Write-Host "[launcher] Running: docker $($composeArgs -join ' ')" -ForegroundColor Cyan
& docker @composeArgs

if ($LASTEXITCODE -ne 0) {
    Write-Error "docker compose failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

# ── 5. Baseline backup ───────────────────────────────────────────────────────
# Snapshots whatever's in the DB right now the stack has just come up. Covers
# the case where the session later ends uncleanly (crash, force-close) and
# stop.ps1's pre-shutdown backup never gets to run.

$backupScript = Join-Path $ScriptDir "scripts\backup-db.ps1"
if (Test-Path $backupScript) {
    Write-Host "[launcher] Taking baseline database backup..." -ForegroundColor Cyan
    try {
        & $backupScript
    } catch {
        Write-Warning "[launcher] Baseline backup failed: $_"
    }
}

# ── 6. Summary ────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "┌─────────────────────────────────────────────────────────────┐" -ForegroundColor Green
Write-Host "│  DroneArjuna GCS is up                                       │" -ForegroundColor Green
Write-Host "│                                                               │" -ForegroundColor Green
Write-Host "│  Frontend  →  http://localhost:3000                          │" -ForegroundColor Green
Write-Host "│  Backend   →  http://localhost:8000/docs                     │" -ForegroundColor Green
Write-Host "│  MailHog   →  http://localhost:8025                          │" -ForegroundColor Green
Write-Host "│  RabbitMQ  →  http://localhost:15672  (da_mq / changeme)     │" -ForegroundColor Green
Write-Host "│                                                               │" -ForegroundColor Green
Write-Host "│  COM bridge PID: $($bridgeProc.Id)                                      │" -ForegroundColor Green
Write-Host "│  Run .\stop.ps1 to stop everything                           │" -ForegroundColor Green
Write-Host "└─────────────────────────────────────────────────────────────┘" -ForegroundColor Green
