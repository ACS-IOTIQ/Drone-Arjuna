#Requires -Version 5.1
<#
.SYNOPSIS
    Adds a docker wrapper to your PowerShell profile so that
    "docker compose up" automatically starts com_bridge.py first.

    Run this script ONCE. After that, just use docker normally.
#>

$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$BridgeScript = Join-Path $ScriptDir "com_bridge.py"
if (-not (Test-Path $BridgeScript)) {
    $BridgeScript = Join-Path $ScriptDir "com_bridge\com_bridge.py"
}
$VbsPath = Join-Path $ScriptDir "start-bridge.vbs"

# ---------------------------------------------------------------------------
# Build the profile block using single-quoted here-string (no expansion here)
# then substitute the actual paths in afterward.
# ---------------------------------------------------------------------------
$profileBlock = '
# DroneArjuna: auto-start com_bridge for Docker Compose workflows
function Get-DroneArjunaBridgeStatus {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:5761/ports" -TimeoutSec 1
        return ($response.Content | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Get-DroneArjunaBridgePortsText {
    param($Status)
    if (-not $Status -or -not $Status.ports) { return "none" }
    $ports = @($Status.ports | ForEach-Object { $_.port })
    if (-not $ports -or $ports.Count -eq 0) { return "none" }
    return ($ports -join ", ")
}

function Start-DroneArjunaBridge {
    $status = Get-DroneArjunaBridgeStatus
    if ($status) {
        if ($status.connected -eq $true -and $status.tcp_port) {
            Write-Host "[bridge] COM bridge ready: $($status.active_port) -> host.docker.internal:$($status.tcp_port)." -ForegroundColor DarkGray
        } else {
            $portsText = Get-DroneArjunaBridgePortsText -Status $status
            if ($portsText -eq "none") {
                Write-Host "[bridge] COM bridge is running and waiting for a Windows serial device. None detected yet." -ForegroundColor Yellow
            } else {
                Write-Host "[bridge] COM bridge is running and waiting to open a serial device. Available ports: $portsText" -ForegroundColor Yellow
            }
        }
        return
    }

    Write-Host "[bridge] Starting com_bridge.py..." -ForegroundColor Cyan
    if (Test-Path "VBSPATH_PLACEHOLDER") {
        Start-Process wscript.exe -ArgumentList """VBSPATH_PLACEHOLDER""" -WindowStyle Hidden
    } else {
        Start-Process python -ArgumentList """BRIDGESCRIPT_PLACEHOLDER""" -WindowStyle Minimized
    }

    Start-Sleep -Seconds 3
    $status = Get-DroneArjunaBridgeStatus
    if ($status -and $status.connected -eq $true) {
        Write-Host "[bridge] Bridge ready: $($status.active_port) -> host.docker.internal:$($status.tcp_port)." -ForegroundColor Green
    } elseif ($status) {
        $portsText = Get-DroneArjunaBridgePortsText -Status $status
        if ($portsText -eq "none") {
            Write-Host "[bridge] Bridge started and is waiting for a Windows serial device. Plug in or replug the drone." -ForegroundColor Yellow
        } else {
            Write-Host "[bridge] Bridge started, but the serial port is not open yet. If one of these is your drone, close Mission Planner/QGC first: $portsText" -ForegroundColor Yellow
        }
    } else {
        Write-Host "[bridge] Bridge did not start. Check bridge.err.log." -ForegroundColor Red
    }
}

function Invoke-Docker {
    $dockerArgs = @($args)
    $argsStr = $dockerArgs -join " "

    if ($dockerArgs.Count -gt 0 -and $dockerArgs[0] -eq "compose" -and $argsStr -notmatch "\b(down|stop)\b") {
        Start-DroneArjunaBridge
    }

    $dockerExe = Get-Command docker -CommandType Application |
                 Select-Object -First 1 -ExpandProperty Source
    & $dockerExe @dockerArgs
}
Set-Alias -Name docker -Value Invoke-Docker -Scope Global -Force
# End DroneArjuna
'

# Substitute real paths into the placeholders
$profileBlock = $profileBlock.Replace("VBSPATH_PLACEHOLDER",      $VbsPath)
$profileBlock = $profileBlock.Replace("BRIDGESCRIPT_PLACEHOLDER", $BridgeScript)

# ---------------------------------------------------------------------------
# Create profile file if it does not exist
# ---------------------------------------------------------------------------
if (-not (Test-Path $PROFILE)) {
    New-Item -ItemType File -Path $PROFILE -Force | Out-Null
    Write-Host "[setup] Created new PowerShell profile at: $PROFILE" -ForegroundColor DarkGray
}

# ---------------------------------------------------------------------------
# Inject once — skip if already present
# ---------------------------------------------------------------------------
$existing = Get-Content $PROFILE -Raw -ErrorAction SilentlyContinue
if ($existing -like "*DroneArjuna*") {
    Write-Host "[setup] Profile already contains DroneArjuna wrapper -- skipping." -ForegroundColor Yellow
} else {
    Add-Content -Path $PROFILE -Value $profileBlock
    Write-Host "[setup] Docker wrapper added to: $PROFILE" -ForegroundColor Green
}

# Apply immediately in this session (no need to reopen PowerShell)
Invoke-Expression $profileBlock

Write-Host ""
Write-Host "Done. From now on, just run:" -ForegroundColor Green
Write-Host "    docker compose up -d --build" -ForegroundColor Cyan
Write-Host ""
Write-Host "com_bridge.py will start automatically before Docker every time." -ForegroundColor Green
Write-Host "To undo: open your profile in Notepad and remove the DroneArjuna block." -ForegroundColor DarkGray
