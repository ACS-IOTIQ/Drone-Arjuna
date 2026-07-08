#Requires -Version 5.1
<#
.SYNOPSIS
    DroneArjuna GCS — full-stack stopper.

.DESCRIPTION
    Stops Docker Compose stack then kills any running com_bridge.py process.

.PARAMETER Volumes
    Pass -Volumes to also destroy Docker named volumes (WARNING: wipes DB data).
#>
param(
    [switch]$Volumes
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# ── 1. Stop Docker Compose ───────────────────────────────────────────────────

$composeArgs = @("compose", "down")
if ($Volumes) {
    Write-Warning "Destroying volumes — all database data will be lost."
    $composeArgs += "-v"
}

Write-Host "[launcher] Stopping Docker Compose stack..." -ForegroundColor Cyan
& docker @composeArgs

# ── 2. Kill com_bridge.py ─────────────────────────────────────────────────────

$bridge = Get-WmiObject Win32_Process -Filter "Name='python.exe' OR Name='python3.exe'" |
          Where-Object { $_.CommandLine -like "*com_bridge.py*" }

if ($bridge) {
    Write-Host "[launcher] Stopping com_bridge.py (PID $($bridge.ProcessId))..." -ForegroundColor Cyan
    $bridge | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host "[launcher] com_bridge.py stopped." -ForegroundColor Green
} else {
    Write-Host "[launcher] com_bridge.py was not running." -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "[launcher] DroneArjuna GCS stopped." -ForegroundColor Green
