# ===================================================================
# backup-db.ps1
# Dumps the DroneArjuna PostgreSQL database (full data + schema) to
# database_dumps\ so a volume loss/reset (docker compose down -v,
# Docker Desktop reset, etc.) doesn't wipe registered drones, drone
# types, missions, and users with no way back.
#
# Usage:
#   .\scripts\backup-db.ps1
#
# Restore:
#   Get-Content database_dumps\dronearjuna_backup_<timestamp>.sql | docker exec -i da_postgres psql -U da_admin -d dronearjuna
# ===================================================================

$ErrorActionPreference = "Stop"

$envFile = Join-Path $PSScriptRoot "..\.env"
$envVars = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)=(.*)$') {
        $envVars[$Matches[1]] = $Matches[2]
    }
}

$pgUser = $envVars["POSTGRES_USER"]
$pgDb   = $envVars["POSTGRES_DB"]

$backupDir = Join-Path $PSScriptRoot "..\database_dumps"
if (-not (Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outFile = Join-Path $backupDir "dronearjuna_backup_$timestamp.sql"

Write-Host "Backing up $pgDb (user: $pgUser) from da_postgres..."
docker exec da_postgres pg_dump -U $pgUser -d $pgDb --no-owner --no-privileges | Out-File -Encoding utf8 $outFile

if ($LASTEXITCODE -ne 0) {
    Write-Error "pg_dump failed - check that the da_postgres container is running."
    exit 1
}

$sizeKb = [math]::Round((Get-Item $outFile).Length / 1024, 1)
Write-Host "Backup written to $outFile ($sizeKb KB)"

# Keep only the last 14 backups so this directory doesn't grow unbounded.
$allBackups = Get-ChildItem $backupDir -Filter "dronearjuna_backup_*.sql" | Sort-Object LastWriteTime -Descending
if ($allBackups.Count -gt 14) {
    $allBackups | Select-Object -Skip 14 | Remove-Item -Force
    Write-Host "Pruned old backups, keeping the 14 most recent."
}
