<#
.SYNOPSIS
    Geofence violation detection test script — no frontend required.

.DESCRIPTION
    Tests the POST /api/flight/missions/{id}/validate endpoint against a
    running DroneArjuna backend. Covers three scenarios:
      1. All waypoints INSIDE the geofence  → valid = true
      2. One waypoint OUTSIDE the geofence  → valid = false, error reported
      3. No geofence defined                → check skipped, valid = true

    GeoJSON coordinate order is [longitude, latitude].
    Waypoint objects use { latitude, longitude } (reversed).

.PARAMETER BaseUrl
    Backend base URL. Defaults to http://localhost:8000.

.PARAMETER Username
    Admin username. Defaults to "admin".

.PARAMETER Password
    Admin password (required — no default for security).

.EXAMPLE
    .\test_geofence.ps1 -Password "YourAdminPass123!"
    .\test_geofence.ps1 -BaseUrl "http://localhost:8000" -Username "admin" -Password "YourPass"

#>
param(
    [string] $BaseUrl  = "http://localhost:8000",
    [string] $Username = "admin",
    [Parameter(Mandatory=$true)]
    [string] $Password
)

$ErrorActionPreference = "Stop"
$headers_json = @{ "Content-Type" = "application/json" }

# ── Colour helpers ─────────────────────────────────────────────────────
function Pass  { param($msg) Write-Host "  [PASS] $msg" -ForegroundColor Green }
function Fail  { param($msg) Write-Host "  [FAIL] $msg" -ForegroundColor Red }
function Info  { param($msg) Write-Host "  [INFO] $msg" -ForegroundColor Cyan }
function Title { param($msg) Write-Host "`n=== $msg ===" -ForegroundColor Yellow }

# ── Geofence: ~1 km² square near Bangalore ────────────────────────────
# Coordinates in GeoJSON order: [longitude, latitude]
# Covers lat 12.965–12.975, lon 77.585–77.595
$GEOFENCE = @{
    type        = "Polygon"
    coordinates = @( @(
        @(77.585, 12.965),   # SW
        @(77.595, 12.965),   # SE
        @(77.595, 12.975),   # NE
        @(77.585, 12.975),   # NW
        @(77.585, 12.965)    # close ring
    ) )
}

# ── Waypoints ──────────────────────────────────────────────────────────
$HOME_WP = @{
    sequence     = 1
    latitude     = 12.970
    longitude    = 77.590
    altitude_m   = 0.0
    altitude_ref = "AGL"
    action       = "none"
    is_home      = $true
}

$WP_INSIDE = @{
    sequence     = 2
    latitude     = 12.972
    longitude    = 77.592
    altitude_m   = 50.0
    altitude_ref = "AGL"
    action       = "none"
}

# Far outside the geofence box (north-west of Bangalore)
$WP_OUTSIDE = @{
    sequence     = 2
    latitude     = 13.000
    longitude    = 77.400
    altitude_m   = 50.0
    altitude_ref = "AGL"
    action       = "none"
}

# ── Tracking ───────────────────────────────────────────────────────────
$created_ids   = @()
$pass_count    = 0
$fail_count    = 0
$TOKEN         = $null

function Assert-Equal {
    param($label, $actual, $expected)
    if ($actual -eq $expected) {
        Pass "$label = $actual"
        $script:pass_count++
    } else {
        Fail "$label expected '$expected', got '$actual'"
        $script:fail_count++
    }
}

function Assert-Contains {
    param($label, $text, $fragment)
    if ($text -match [regex]::Escape($fragment)) {
        Pass "$label contains '$fragment'"
        $script:pass_count++
    } else {
        Fail "$label missing '$fragment'. Got: $text"
        $script:fail_count++
    }
}

# ══════════════════════════════════════════════════════════════════
# Step 1 — Authenticate
# ══════════════════════════════════════════════════════════════════
Title "Step 1: Authenticate"

$login_body = @{ username = $Username; password = $Password } | ConvertTo-Json
try {
    $login_resp = Invoke-RestMethod -Method Post `
        -Uri "$BaseUrl/api/auth/login" `
        -Headers $headers_json `
        -Body $login_body
    $TOKEN = $login_resp.access_token
    Pass "Login successful — token acquired"
    $pass_count++
} catch {
    Fail "Login failed: $_"
    $fail_count++
    exit 1
}

$auth_headers = @{
    "Content-Type"  = "application/json"
    "Authorization" = "Bearer $TOKEN"
}

# ── Helper: create a mission and return its id ─────────────────────────
function New-Mission {
    param(
        [string]   $Name,
        [array]    $Waypoints,
        [hashtable] $Geofence = $null
    )
    $body = @{
        name         = $Name
        mission_type = "ISR"
        waypoints    = $Waypoints
    }
    if ($null -ne $Geofence) {
        $body["geofence"] = $Geofence
    }
    $resp = Invoke-RestMethod -Method Post `
        -Uri "$BaseUrl/api/flight/missions" `
        -Headers $auth_headers `
        -Body ($body | ConvertTo-Json -Depth 10)
    $script:created_ids += $resp.id
    return $resp.id
}

# ── Helper: validate a mission and return the result ──────────────────
function Invoke-Validate {
    param([int] $MissionId)
    return Invoke-RestMethod -Method Post `
        -Uri "$BaseUrl/api/flight/missions/$MissionId/validate" `
        -Headers $auth_headers
}

# ── Helper: delete a mission ──────────────────────────────────────────
function Remove-Mission {
    param([int] $Id)
    try {
        Invoke-RestMethod -Method Delete `
            -Uri "$BaseUrl/api/flight/missions/$Id" `
            -Headers $auth_headers | Out-Null
    } catch {}
}

# ══════════════════════════════════════════════════════════════════
# Scenario A — All waypoints INSIDE geofence → valid = true
# ══════════════════════════════════════════════════════════════════
Title "Scenario A: All waypoints inside geofence"

$mid_a = New-Mission -Name "GF-Test-Inside" `
    -Waypoints @($HOME_WP, $WP_INSIDE) `
    -Geofence $GEOFENCE

Info "Mission ID: $mid_a"
Info "Geofence:  lat [12.965 – 12.975], lon [77.585 – 77.595]"
Info "Home:      lat=12.970, lon=77.590  → INSIDE"
Info "Target:    lat=12.972, lon=77.592  → INSIDE"

$result_a = Invoke-Validate -MissionId $mid_a
Info "Response:  valid=$($result_a.valid), errors=$($result_a.errors.Count)"

Assert-Equal "valid"       $result_a.valid   $true
Assert-Equal "error count" $result_a.errors.Count  0

# ══════════════════════════════════════════════════════════════════
# Scenario B — One waypoint OUTSIDE geofence → valid = false
# ══════════════════════════════════════════════════════════════════
Title "Scenario B: Waypoint outside geofence"

$mid_b = New-Mission -Name "GF-Test-Outside" `
    -Waypoints @($HOME_WP, $WP_OUTSIDE) `
    -Geofence $GEOFENCE

Info "Mission ID: $mid_b"
Info "Geofence:  lat [12.965 – 12.975], lon [77.585 – 77.595]"
Info "Home:      lat=12.970, lon=77.590  → INSIDE"
Info "Violating: lat=13.000, lon=77.400  → OUTSIDE (far north-west)"

$result_b = Invoke-Validate -MissionId $mid_b
Info "Response:  valid=$($result_b.valid), errors=$($result_b.errors.Count)"
if ($result_b.errors.Count -gt 0) {
    Info "Error[0]:  $($result_b.errors[0])"
}

Assert-Equal "valid"       $result_b.valid   $false
if ($result_b.errors.Count -ge 1) {
    Assert-Contains "error[0]" $result_b.errors[0] "outside the defined geofence"
    Assert-Contains "error[0] seq" $result_b.errors[0] "2"        # waypoint sequence
    Assert-Contains "error[0] lat" $result_b.errors[0] "13.00000" # lat formatted to 5dp
    Assert-Contains "error[0] lon" $result_b.errors[0] "77.40000" # lon formatted to 5dp
    $pass_count++
} else {
    Fail "No errors returned — expected at least 1 geofence error"
    $fail_count++
}

# ══════════════════════════════════════════════════════════════════
# Scenario C — No geofence defined → check skipped, valid = true
# ══════════════════════════════════════════════════════════════════
Title "Scenario C: No geofence (check skipped)"

$mid_c = New-Mission -Name "GF-Test-NoFence" `
    -Waypoints @($HOME_WP, $WP_OUTSIDE)   # same violating waypoint, but NO geofence

Info "Mission ID: $mid_c"
Info "Geofence:   none"
Info "Waypoints:  same coords that violated in Scenario B"

$result_c = Invoke-Validate -MissionId $mid_c
Info "Response:  valid=$($result_c.valid), errors=$($result_c.errors.Count)"

Assert-Equal "valid" $result_c.valid $true
$gf_errors = @($result_c.errors | Where-Object { $_ -match "geofence|outside" })
Assert-Equal "geofence error count" $gf_errors.Count 0

# ══════════════════════════════════════════════════════════════════
# Scenario D — Malformed geofence → warning issued, no hard error
# ══════════════════════════════════════════════════════════════════
Title "Scenario D: Malformed geofence format"

$mid_d = New-Mission -Name "GF-Test-Malformed" `
    -Waypoints @($HOME_WP, $WP_OUTSIDE) `
    -Geofence @{ type = "Polygon" }   # missing 'coordinates' key

Info "Mission ID: $mid_d"
Info "Geofence:  {type:'Polygon'}  (coordinates key missing)"

$result_d = Invoke-Validate -MissionId $mid_d
Info "Response:  valid=$($result_d.valid), warnings=$($result_d.warnings.Count)"
if ($result_d.warnings.Count -gt 0) { Info "Warning[0]: $($result_d.warnings[0])" }

$gf_warnings = @($result_d.warnings | Where-Object { $_ -match "geofence" })
if ($gf_warnings.Count -ge 1) {
    Pass "Geofence warning issued: '$($gf_warnings[0])'"
    $pass_count++
} else {
    Fail "Expected a geofence format warning, got: $($result_d.warnings)"
    $fail_count++
}
# Should NOT have an 'outside' hard error (check was skipped)
$outside_errors = @($result_d.errors | Where-Object { $_ -match "outside" })
Assert-Equal "outside errors" $outside_errors.Count 0

# ══════════════════════════════════════════════════════════════════
# Cleanup
# ══════════════════════════════════════════════════════════════════
Title "Cleanup"
foreach ($id in $created_ids) {
    Remove-Mission -Id $id
    Info "Deleted mission $id"
}

# ══════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════
$total = $pass_count + $fail_count
Write-Host ""
Write-Host "══════════════════════════════════════════" -ForegroundColor White
if ($fail_count -eq 0) {
    Write-Host "  RESULT: ALL $total CHECKS PASSED" -ForegroundColor Green
} else {
    Write-Host "  RESULT: $fail_count/$total CHECKS FAILED" -ForegroundColor Red
}
Write-Host "══════════════════════════════════════════" -ForegroundColor White

if ($fail_count -gt 0) { exit 1 }
