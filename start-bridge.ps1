param(
    [string]$ComPort = "auto",
    [int]$Baud = 115200,
    [int]$TcpPort = 5762
)

$ErrorActionPreference = "Stop"

$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$Bridge = Join-Path $Repo "com_bridge.py"
$OutLog = Join-Path $Repo "bridge.out.log"
$ErrLog = Join-Path $Repo "bridge.err.log"

if (-not (Test-Path $Bridge)) {
    throw "Bridge script not found: $Bridge"
}

python -u $Bridge $ComPort $Baud $TcpPort 1>> $OutLog 2>> $ErrLog
