#Requires -Version 5.1
<#
.SYNOPSIS
    Registers com_bridge.py as a Windows Task Scheduler job that starts
    automatically at user logon. After this runs, com_bridge.py is always
    alive before any docker compose command is issued.

.PARAMETER ComPort
    COM port to forward, e.g. COM3. Default "auto".

.PARAMETER Baud
    Baud rate. Default 115200 (USB direct Pixhawk). Use 57600 for SiK radios.

.PARAMETER Uninstall
    Remove the scheduled task and stop any running instance.

.EXAMPLE
    .\install-bridge-service.ps1
    .\install-bridge-service.ps1 -ComPort COM4 -Baud 57600
    .\install-bridge-service.ps1 -Uninstall
#>
param(
    [string]$ComPort = "auto",
    [int]$Baud       = 115200,
    [switch]$Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$TaskName  = "DroneArjunaCOMBridge"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Locate com_bridge.py
$BridgeScript = Join-Path $ScriptDir "com_bridge.py"
if (-not (Test-Path $BridgeScript)) {
    $BridgeScript = Join-Path $ScriptDir "com_bridge\com_bridge.py"
}
if (-not (Test-Path $BridgeScript)) {
    Write-Error "com_bridge.py not found under $ScriptDir"
    exit 1
}

# ---------------------------------------------------------------------------
# Uninstall path
# ---------------------------------------------------------------------------
if ($Uninstall) {
    $running = Get-WmiObject Win32_Process -Filter "Name='python.exe' OR Name='python3.exe'" |
               Where-Object { $_.CommandLine -like "*com_bridge.py*" }
    if ($running) {
        $running | ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Write-Host "[service] Stopped running com_bridge.py" -ForegroundColor Yellow
    }
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "[service] Scheduled task '$TaskName' removed." -ForegroundColor Green
    } else {
        Write-Host "[service] Task '$TaskName' was not registered." -ForegroundColor DarkGray
    }
    exit 0
}

# ---------------------------------------------------------------------------
# Check pyserial
# ---------------------------------------------------------------------------
Write-Host "[service] Checking pyserial..." -ForegroundColor DarkGray
$pyCheck = & python -c "import serial; print('ok')" 2>&1
if ($pyCheck -notmatch "ok") {
    Write-Host "[service] pyserial not found - installing..." -ForegroundColor Yellow
    & python -m pip install pyserial --quiet
}

# ---------------------------------------------------------------------------
# Resolve python.exe full path (Task Scheduler needs absolute path)
# ---------------------------------------------------------------------------
$PythonExe = (Get-Command python -ErrorAction Stop).Source
Write-Host "[service] Python: $PythonExe" -ForegroundColor DarkGray
Write-Host "[service] Bridge: $BridgeScript" -ForegroundColor DarkGray

# ---------------------------------------------------------------------------
# Build Task Scheduler components
# ---------------------------------------------------------------------------
$Action = New-ScheduledTaskAction `
    -Execute  $PythonExe `
    -Argument "`"$BridgeScript`" $ComPort $Baud" `
    -WorkingDirectory $ScriptDir

$Trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit  (New-TimeSpan -Hours 0) `
    -RestartCount        3 `
    -RestartInterval     (New-TimeSpan -Minutes 1) `
    -MultipleInstances   IgnoreNew `
    -StartWhenAvailable

$Principal = New-ScheduledTaskPrincipal `
    -UserId    "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel  Limited

# ---------------------------------------------------------------------------
# Register or update the task
# ---------------------------------------------------------------------------
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "[service] Updating existing task '$TaskName'..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName    $TaskName `
    -Action      $Action `
    -Trigger     $Trigger `
    -Settings    $Settings `
    -Principal   $Principal `
    -Description "DroneArjuna COM-to-TCP bridge. Forwards Windows serial port to Docker backend." |
    Out-Null

Write-Host "[service] Scheduled task '$TaskName' registered." -ForegroundColor Green

# ---------------------------------------------------------------------------
# Start it right now (no need to log out/in)
# ---------------------------------------------------------------------------
Write-Host "[service] Starting bridge now..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
try {
    $status = Invoke-RestMethod -Uri "http://localhost:5761/ports" -TimeoutSec 2
    if ($status.connected) {
        Write-Host "[service] Bridge ready - $($status.active_port) @ $($status.baud) baud -> TCP:$($status.tcp_port)" -ForegroundColor Green
    } else {
        Write-Host "[service] Bridge running, no serial device detected yet (will connect when plugged in)." -ForegroundColor Yellow
    }
} catch {
    Write-Host "[service] Bridge started but discovery endpoint not responding yet." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done. com_bridge.py will now start automatically at every login." -ForegroundColor Green
Write-Host "From now on just run:" -ForegroundColor Green
Write-Host ""
Write-Host "    docker compose up -d --build" -ForegroundColor Cyan
Write-Host ""
Write-Host "To remove: .\install-bridge-service.ps1 -Uninstall" -ForegroundColor DarkGray
