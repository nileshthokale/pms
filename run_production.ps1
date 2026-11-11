<#
.SYNOPSIS
    Launch the Pharmacy Management System against its existing production database.

.DESCRIPTION
    Selects only data\pharmacy.db, refuses to create it if missing, and
    clears staging/test-only startup flags for this process. Use "check"
    as the first argument to run preflight validation without opening the UI.
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("run", "check")]
    [string]$Action = "run"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$ProductionDb = [System.IO.Path]::GetFullPath(
    (Join-Path $ProjectRoot "data\pharmacy.db")
)
$StagingDb = [System.IO.Path]::GetFullPath(
    (Join-Path $ProjectRoot "staging\pharmacy_staging.db")
)
$MainScript = Join-Path $ProjectRoot "main.py"

if (-not (Test-Path -LiteralPath $ProductionDb -PathType Leaf)) {
    Write-Error "Production database not found at '$ProductionDb'. Refusing to create an empty database."
    exit 1
}
if ($ProductionDb -eq $StagingDb) {
    Write-Error "Production and staging database paths must be different."
    exit 1
}
if (-not (Test-Path -LiteralPath $MainScript -PathType Leaf)) {
    Write-Error "Application entry point not found at '$MainScript'."
    exit 1
}

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    Write-Error "Python was not found in PATH."
    exit 1
}

$EnvironmentNames = @(
    "PHARMACY_DB",
    "PHARMACY_DB_PATH",
    "PHARMACY_MODE",
    "PHARMACY_STAGING_MODE",
    "PHARMACY_TEST_PROTECTED_DB",
    "PHARMACY_TEST_SAFE_DB",
    "PHARMACY_TEST_RELEASE",
    "PHARMACY_REQUIRE_EXISTING_DB",
    "PYTHONUNBUFFERED"
)
$PreviousEnvironment = @{}
foreach ($Name in $EnvironmentNames) {
    $PreviousEnvironment[$Name] = [System.Environment]::GetEnvironmentVariable(
        $Name,
        "Process"
    )
}

$ExitCode = 0
try {
    foreach ($Name in $EnvironmentNames) {
        Remove-Item -Path "Env:\$Name" -ErrorAction SilentlyContinue
    }
    $env:PHARMACY_MODE = "PRODUCTION"
    $env:PHARMACY_DB = $ProductionDb
    $env:PYTHONUNBUFFERED = "1"

    $PreflightCode = @"
import sqlite3
import sys
from pathlib import Path
from database.connection import get_db_path

expected = Path(sys.argv[1]).resolve()
actual = Path(get_db_path()).resolve()
if actual != expected:
    raise SystemExit(f'Production database selection mismatch: {actual} != {expected}')
with sqlite3.connect(actual.as_uri() + '?mode=ro', uri=True) as conn:
    result = conn.execute('PRAGMA integrity_check').fetchone()
    if result != ('ok',):
        raise SystemExit(f'Production database integrity check failed: {result}')
    tables = {
        row[0] for row in conn.execute(
            'SELECT name FROM sqlite_master WHERE type = ?',
            ('table',),
        )
    }
    required = {'items', 'sales_invoices', 'purchase_invoices', 'suppliers'}
    missing = required - tables
    if missing:
        raise SystemExit(f'Production database is missing required tables: {sorted(missing)}')
    for table in ('items', 'sales_invoices'):
        count = conn.execute('SELECT count(*) FROM ' + table).fetchone()[0]
        if count < 1:
            raise SystemExit(f'Production database contains no records in {table}')
print(f'PRODUCTION database verified: {actual}')
print('Pharmacy schema and business records: present')
print('SQLite integrity check: ok')
"@

    Push-Location $ProjectRoot
    & $Python.Source -c $PreflightCode $ProductionDb
    if ($LASTEXITCODE -ne 0) {
        $ExitCode = $LASTEXITCODE
    } elseif ($Action -eq "check") {
        Write-Host "[CHECK COMPLETE] Production preflight passed. No application was started." -ForegroundColor Green
    } else {
        Write-Host "Launching Pharmacy Management System in PRODUCTION mode." -ForegroundColor Green
        Write-Host "Production database: $ProductionDb"
        & $Python.Source -u $MainScript
        $ExitCode = $LASTEXITCODE
    }
} finally {
    if ((Get-Location).Path -eq $ProjectRoot) {
        Pop-Location
    }
    foreach ($Name in $EnvironmentNames) {
        [System.Environment]::SetEnvironmentVariable(
            $Name,
            $PreviousEnvironment[$Name],
            "Process"
        )
    }
}

if ($ExitCode -ne 0) {
    exit $ExitCode
}
