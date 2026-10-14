# Start DroneArjuna with NO internet access (e.g. on the ExpressLRS TX Backpack Wi-Fi).
# That network's DNS points every hostname at 10.0.0.1, so image pulls and --build fail.
# This uses only images already on this PC and skips pgAdmin/MailHog (not needed to fly).
#
# Usage: .\start-offline.ps1
# Rebuild images (--build) only while on a network with internet.

Set-Location $PSScriptRoot

# Accept MAVLink UDP from the Wi-Fi adapter, not just loopback (shell env overrides .env).
$env:RADIO_BIND_ADDR = "0.0.0.0"

$needed = @(
    "dronearjuna-backend:latest", "dronearjuna-frontend:latest",
    "postgis/postgis:15-3.3", "timescale/timescaledb:latest-pg15", "redis:7-alpine",
    "rabbitmq:4.3.3-management-alpine", "bitnamilegacy/minio:2025.7.23-debian-12-r5",
    "docker.elastic.co/elasticsearch/elasticsearch:8.12.0"
)
$have = docker images --format "{{.Repository}}:{{.Tag}}"
$missing = $needed | Where-Object { $_ -notin $have }
if ($missing) {
    Write-Host "Missing local images (need internet once to fetch/build):" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "  $_" }
    exit 1
}

# USB flight controller or ELRS radio: the Windows COM bridge forwards the COM port to the backend.
# (Normally your PowerShell profile starts it on `docker compose`; do it here too.)
# "auto" makes the bridge listen for a MAVLink heartbeat at 460800 (ELRS radio USB),
# 115200, 57600 (SiK), 921600 and 230400 and keep the one that answers.
# Pin a speed instead with: $env:BRIDGE_BAUD = 57600
$bridgeBaud = if ($env:BRIDGE_BAUD) { $env:BRIDGE_BAUD } else { "auto" }
try {
    Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5761/ports -TimeoutSec 2 | Out-Null
    Write-Host "[bridge] COM bridge already running." -ForegroundColor DarkGray
} catch {
    Write-Host "[bridge] Starting COM bridge (waits for a USB flight controller)..." -ForegroundColor Cyan
    Start-Process powershell.exe -WindowStyle Hidden -WorkingDirectory $PSScriptRoot -ArgumentList `
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSScriptRoot\start-bridge.ps1`"", "auto", $bridgeBaud, "5762"
}

docker compose up -d --no-build --pull never backend frontend
docker compose ps
