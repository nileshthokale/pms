<#
.SYNOPSIS
    Safe Staging Launcher for Pharmacy Management System.

.DESCRIPTION
    Launches the Pharmacy Management System exclusively using the isolated
    staging database: staging/pharmacy_staging.db.

    Safety Guarantees:
    - Never modifies or promotes to data/pharmacy.db.
    - Never creates a new empty database if staging is missing.
    - Intercepts connection.py to guard against fallback to live production.
    - Visibly displays [STAGING / AUDIT MODE] in the window title bar.
    - Displays database location in Master -> Backup & Restore.
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Action = "run",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
if (-not $ProjectRoot) {
    $ProjectRoot = (Get-Location).Path
}

$StagingDb = Join-Path $ProjectRoot "staging\pharmacy_staging.db"
$ActiveDb = Join-Path $ProjectRoot "data\pharmacy.db"
$ScriptPath = Join-Path $ProjectRoot "launch_staging.py"

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "         PHARMACY MANAGEMENT SYSTEM -- STAGING LAUNCHER" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host " Project Directory : $ProjectRoot"
Write-Host " Staging Database  : $StagingDb"
Write-Host " Protected Live DB : $ActiveDb"
Write-Host "------------------------------------------------------------------------------"

# 1. Check if Python is available
$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    Write-Host "[ERROR] Python was not found in PATH." -ForegroundColor Red
    Write-Host "Please install Python 3.11+ and ensure it is available in your PATH." -ForegroundColor Yellow
    exit 1
}

# 2. Refuse to launch if staging database does not exist (do not create empty DB)
if (-not (Test-Path -Path $StagingDb -PathType Leaf)) {
    Write-Host "[CRITICAL ERROR] Staging database not found at:" -ForegroundColor Red
    Write-Host "  $StagingDb" -ForegroundColor White
    Write-Host "Refusing to launch. The staging database must be initialized first." -ForegroundColor Red
    Write-Host "Will NOT create a new empty database." -ForegroundColor Yellow
    exit 1
}

# 3. Check staging database size (must be substantial, ~45 MB)
$StagingItem = Get-Item $StagingDb
if ($StagingItem.Length -lt 1000000) {
    $FormattedSize = "{0:N0}" -f $StagingItem.Length
    Write-Host "[CRITICAL ERROR] Staging database file is suspiciously small ($FormattedSize bytes)." -ForegroundColor Red
    Write-Host "Expected ~45 MB. Refusing to launch." -ForegroundColor Yellow
    exit 1
}

# 4. Strict Path Separation Check
$ResolvedStaging = [System.IO.Path]::GetFullPath($StagingDb).ToLowerInvariant()
$ResolvedActive = [System.IO.Path]::GetFullPath($ActiveDb).ToLowerInvariant()

if ($ResolvedStaging -eq $ResolvedActive) {
    Write-Host "[FATAL SAFETY REFUSAL] Staging database path resolves to the ACTIVE production database:" -ForegroundColor Red
    Write-Host "  $ActiveDb" -ForegroundColor White
    Write-Host "Refusing to start staging launcher against production database!" -ForegroundColor Red
    exit 1
}

# 5. Check for duplicate running staging instances
$RunningInstances = Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%launch_staging.py%'" -ErrorAction SilentlyContinue
if ($RunningInstances) {
    $RunningPids = ($RunningInstances | Select-Object -ExpandProperty ProcessId) -join ', '
    Write-Host "[WARNING] An instance of launch_staging.py is already running (PID: $RunningPids)." -ForegroundColor Yellow
    Write-Host "Please close the existing instance or terminate PID $RunningPids to avoid database lock conflicts." -ForegroundColor Yellow
}

# 6. Set session environment variables
$env:PHARMACY_DB = $StagingDb
$env:PHARMACY_TEST_PROTECTED_DB = $ActiveDb
$env:PHARMACY_TEST_SAFE_DB = $StagingDb
$env:PHARMACY_STAGING_MODE = "1"
$env:PYTHONUNBUFFERED = "1"

$SizeMb = [math]::Round($StagingItem.Length / 1MB, 2)
Write-Host "[PREFLIGHT PASS] Staging database verified ($SizeMb MB)." -ForegroundColor Green
Write-Host "[PREFLIGHT PASS] Environment guarded: fallback to data/pharmacy.db is blocked." -ForegroundColor Green
Write-Host "------------------------------------------------------------------------------"

# "check" is a validation-only action: it must never print or perform a launch.
$IsCheckOnly = $Action -in @("check", "test", "preflight", "dry-run")
if ($IsCheckOnly) {
    Write-Host "Running preflight checks only (the application will NOT be started)..." -ForegroundColor Cyan
} else {
    Write-Host "Launching application in Staging Mode..." -ForegroundColor Cyan
}
Write-Host ""

$ExitCode = 0
try {
    if ($IsCheckOnly) {
        & python -u $ScriptPath --check
    } else {
        & python -u $ScriptPath
    }
    $ExitCode = $LASTEXITCODE
    if ($null -ne $ExitCode -and $ExitCode -ne 0) {
        Write-Host ""
        Write-Host "[EXIT] Application process exited with code $ExitCode." -ForegroundColor Red
        Write-Host "       The complete startup error output is printed above." -ForegroundColor Yellow
    }
}
finally {
    # Clean up environment variables in PowerShell session
    Remove-Item Env:\PHARMACY_DB -ErrorAction SilentlyContinue
    Remove-Item Env:\PHARMACY_TEST_PROTECTED_DB -ErrorAction SilentlyContinue
    Remove-Item Env:\PHARMACY_TEST_SAFE_DB -ErrorAction SilentlyContinue
    Remove-Item Env:\PHARMACY_STAGING_MODE -ErrorAction SilentlyContinue
    Remove-Item Env:\PYTHONUNBUFFERED -ErrorAction SilentlyContinue
}

if ($IsCheckOnly) {
    if ($ExitCode -eq 0) {
        Write-Host "[CHECK COMPLETE] Preflight passed. No application process was started." -ForegroundColor Green
    } else {
        Write-Host "[CHECK FAILED] Preflight did not pass (exit code $ExitCode)." -ForegroundColor Red
        exit $ExitCode
    }
}
