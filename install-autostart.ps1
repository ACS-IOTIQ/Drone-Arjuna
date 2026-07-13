#Requires -Version 5.1
<#
.SYNOPSIS
    Adds com_bridge.py to the Windows Startup folder so it starts
    automatically at every login - no Task Scheduler, no admin rights needed.

.PARAMETER ComPort
    COM port to forward, e.g. COM6. Default "auto".

.PARAMETER Baud
    Baud rate. Default 115200.

.PARAMETER Uninstall
    Remove the startup shortcut and stop any running instance.

.EXAMPLE
    .\install-autostart.ps1
    .\install-autostart.ps1 -ComPort COM6 -Baud 115200
    .\install-autostart.ps1 -Uninstall
#>
param(
    [string]$ComPort = "auto",
    [int]$Baud       = 115200,
    [switch]$Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartupFolder = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
$ShortcutPath  = Join-Path $StartupFolder "DroneArjunaCOMBridge.lnk"
$VbsPath       = Join-Path $ScriptDir "start-bridge.vbs"

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
# Uninstall
# ---------------------------------------------------------------------------
if ($Uninstall) {
    $running = Get-WmiObject Win32_Process -Filter "Name='python.exe' OR Name='python3.exe'" |
               Where-Object { $_.CommandLine -like "*com_bridge*" }
    if ($running) {
        $running | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Write-Host "[autostart] Stopped com_bridge.py" -ForegroundColor Yellow
    }
    if (Test-Path $ShortcutPath) { Remove-Item $ShortcutPath -Force }
    if (Test-Path $VbsPath)      { Remove-Item $VbsPath -Force }
    Write-Host "[autostart] Startup entry removed." -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------------------
# Check pyserial
# ---------------------------------------------------------------------------
$pyCheck = & python -c "import serial; print('ok')" 2>&1
if ($pyCheck -notmatch "ok") {
    Write-Host "[autostart] Installing pyserial..." -ForegroundColor Yellow
    & python -m pip install pyserial --quiet
}

$PythonExe = (Get-Command python -ErrorAction Stop).Source

# ---------------------------------------------------------------------------
# Create a .vbs launcher (runs Python hidden - no console window on startup)
# ---------------------------------------------------------------------------
$vbsContent = @"
Set oShell = CreateObject("WScript.Shell")
oShell.Run """$PythonExe"" ""$BridgeScript"" $ComPort $Baud", 0, False
"@
Set-Content -Path $VbsPath -Value $vbsContent -Encoding ASCII
Write-Host "[autostart] Created launcher: $VbsPath" -ForegroundColor DarkGray

# ---------------------------------------------------------------------------
# Create shortcut in Startup folder pointing to the .vbs
# ---------------------------------------------------------------------------
$shell    = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath       = "wscript.exe"
$shortcut.Arguments        = "`"$VbsPath`""
$shortcut.WorkingDirectory = $ScriptDir
$shortcut.Description      = "DroneArjuna COM bridge - forwards serial port to Docker"
$shortcut.Save()

Write-Host "[autostart] Startup shortcut created: $ShortcutPath" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Kill any stale instance and start it right now
# ---------------------------------------------------------------------------
$running = Get-WmiObject Win32_Process -Filter "Name='python.exe' OR Name='python3.exe'" |
           Where-Object { $_.CommandLine -like "*com_bridge*" }
if ($running) {
    $running | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 500
}

Write-Host "[autostart] Starting bridge now..." -ForegroundColor Cyan
& wscript.exe $VbsPath
Start-Sleep -Seconds 3

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
try {
    $status = Invoke-RestMethod -Uri "http://localhost:5761/ports" -TimeoutSec 2
    if ($status.connected) {
        Write-Host "[autostart] Bridge ready - $($status.active_port) forwarded to TCP:$($status.tcp_port)" -ForegroundColor Green
    } else {
        Write-Host "[autostart] Bridge running, no serial device yet (will connect when plugged in)." -ForegroundColor Yellow
    }
} catch {
    Write-Host "[autostart] Bridge may still be starting up." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done. com_bridge.py will now start automatically at every Windows login." -ForegroundColor Green
Write-Host "Just run:  docker compose up -d --build" -ForegroundColor Cyan
Write-Host "To remove: .\install-autostart.ps1 -Uninstall" -ForegroundColor DarkGray
