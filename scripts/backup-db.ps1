# ===================================================================
# backup-db.ps1
# Dumps both DroneArjuna PostgreSQL databases (full data + schema) to
# database_dumps\ so a volume loss/reset (docker compose down -v,
# Docker Desktop reset, etc.) doesn't wipe registered drones, drone
# types, missions, users, and telemetry history with no way back.
#
#   - da_postgres  (main app DB: users, drones, missions, ...)
#   - da_timescale (telemetry time-series hypertables)
#
# Usage:
#   .\scripts\backup-db.ps1
#
# Restore:
#   Get-Content database_dumps\dronearjuna_backup_<timestamp>.sql | docker exec -i da_postgres psql -U da_admin -d dronearjuna
#   Get-Content database_dumps\da_telemetry_backup_<timestamp>.sql | docker exec -i da_timescale psql -U da_admin -d da_telemetry
# ===================================================================

$ErrorActionPreference = "Stop"

$envFile = Join-Path $PSScriptRoot "..\.env"
$envVars = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)=(.*)$') {
        $envVars[$Matches[1]] = $Matches[2]
    }
}

$pgUser        = $envVars["POSTGRES_USER"]
$pgDb          = $envVars["POSTGRES_DB"]
$timescaleDb   = $envVars["TIMESCALE_DB"]
if (-not $timescaleDb) { $timescaleDb = "da_telemetry" }

$backupDir = Join-Path $PSScriptRoot "..\database_dumps"
if (-not (Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

function Backup-Database {
    param(
        [string]$ContainerName,
        [string]$DbUser,
        [string]$DbName,
        [string]$FilePrefix
    )

    $outFile = Join-Path $backupDir "${FilePrefix}_backup_$timestamp.sql"
    Write-Host "Backing up $DbName (user: $DbUser) from ${ContainerName}..."
    docker exec $ContainerName pg_dump -U $DbUser -d $DbName --no-owner --no-privileges | Out-File -Encoding utf8 $outFile

    if ($LASTEXITCODE -ne 0) {
        Write-Error "pg_dump failed for $DbName - check that the $ContainerName container is running."
        exit 1
    }

    $sizeKb = [math]::Round((Get-Item $outFile).Length / 1024, 1)
    Write-Host "Backup written to $outFile ($sizeKb KB)"

    # Keep only the last 14 backups per database so this directory doesn't grow unbounded.
    $allBackups = Get-ChildItem $backupDir -Filter "${FilePrefix}_backup_*.sql" | Sort-Object LastWriteTime -Descending
    if ($allBackups.Count -gt 14) {
        $allBackups | Select-Object -Skip 14 | Remove-Item -Force
        Write-Host "Pruned old $FilePrefix backups, keeping the 14 most recent."
    }
}

Backup-Database -ContainerName "da_postgres"  -DbUser $pgUser -DbName $pgDb        -FilePrefix "dronearjuna"
Backup-Database -ContainerName "da_timescale" -DbUser $pgUser -DbName $timescaleDb -FilePrefix "da_telemetry"
