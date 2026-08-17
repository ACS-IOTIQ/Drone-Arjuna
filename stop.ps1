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

# ── 1. Back up the databases before touching anything ───────────────────────
# Always runs, so a plain "down" as well as a "-Volumes" teardown both leave
# a fresh dump behind — a wiped volume is then always recoverable.

$backupScript = Join-Path $ScriptDir "scripts\backup-db.ps1"
if (Test-Path $backupScript) {
    Write-Host "[launcher] Backing up databases before shutdown..." -ForegroundColor Cyan
    try {
        & $backupScript
    } catch {
        Write-Warning "[launcher] Backup failed: $_"
        if ($Volumes) {
            $confirm = Read-Host "Backup failed and -Volumes will destroy all DB data. Continue anyway? (y/N)"
            if ($confirm -ne "y") {
                Write-Host "[launcher] Aborted — no data was destroyed." -ForegroundColor Yellow
                exit 1
            }
        }
    }
} else {
    Write-Warning "[launcher] scripts\backup-db.ps1 not found — skipping pre-shutdown backup."
}

# ── 2. Stop Docker Compose ───────────────────────────────────────────────────

$composeArgs = @("compose", "down")
if ($Volumes) {
    Write-Warning "Destroying volumes — all database data will be lost (a backup was just taken above)."
    $composeArgs += "-v"
}

Write-Host "[launcher] Stopping Docker Compose stack..." -ForegroundColor Cyan
& docker @composeArgs

# ── 3. Kill com_bridge.py ─────────────────────────────────────────────────────

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
